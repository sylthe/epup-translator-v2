# epub-translator

Application CLI Python qui traduit des romans `.epub` anglais en français avec Claude AI. Elle reproduit le workflow d'un traducteur professionnel : analyse littéraire complète, puis traduction chapitre par chapitre guidée par cette analyse.

---

## Pipeline

```
┌─────────────┐     ┌───────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  EXTRACTION  │ ──▶ │  PHASE 1 : ANALYSE │ ──▶ │ PHASE 2 : TRAD.  │ ──▶ │ RECONSTRUCTION │
│  ePub → HTML │     │  6 appels LLM      │     │  Chapitre/chap.  │     │  HTML → ePub   │
└─────────────┘     └───────────────────┘     └──────────────────┘     └───────────────┘
```

1. **Extraction** — parse l'ePub, isole les nœuds texte en préservant l'arbre HTML (classes CSS, lettrines, formatage inline)
2. **Analyse (Phase 1)** — 6 appels API séquentiels (Haiku) produisent un profil JSON structuré (personnages, ton, glossaire, références culturelles…). Affiche le % du livre couvert.
3. **Traduction (Phase 2)** — chaque chapitre est découpé en segments, traduit avec l'analyse injectée en contexte (cache prompt). Après chaque chapitre, un appel Haiku enrichit le glossaire et les personnages.
4. **Reconstruction** — le texte traduit est réinjecté dans l'arbre HTML original et un nouvel ePub est écrit ; un badge « IA » est composité sur la couverture si `badge-IA.png` est présent.

---

## Installation

```bash
pip install -e .
```

Copier le fichier d'exemple et renseigner la clé API Anthropic :

```bash
cp .env.example .env
# puis éditer .env :
# ANTHROPIC_API_KEY=sk-ant-...
```

> **Alternative** : exporter la variable directement dans le shell.
> ```bash
> export ANTHROPIC_API_KEY="sk-ant-..."
> ```

---

## Usage

```bash
# Traduction complète
python -m src.main translate roman.epub -o roman_fr.epub

# Analyse seule (révision avant traduction)
python -m src.main translate roman.epub --analysis-only

# Reprendre une traduction interrompue
python -m src.main translate roman.epub --resume

# Utiliser une analyse existante (éventuellement retouchée à la main)
python -m src.main translate roman.epub --skip-analysis

# Retraduire un chapitre spécifique (accepte numéro, titre, fichier HTML ou fichier cache)
python -m src.main translate roman.epub -r 5
python -m src.main translate roman.epub -r "The Awakening"
python -m src.main translate roman.epub -r chapter05.xhtml
python -m src.main translate roman.epub -r chapter_0004.json

# Vider le cache d'un livre
python -m src.main clear-cache roman.epub

# Valider et auto-corriger un ePub
python -m src.main validate roman.epub
python -m src.main validate roman.epub --no-fix   # rapport seul, sans correction
python -m src.main validate roman.epub -o corrected.epub
```

---

## Fonctionnalités clés

### Préservation de la mise en page
- **Arbre HTML intact** — reconstruction zipfile byte-for-byte ; seuls les fichiers HTML traduits sont remplacés (CSS, polices, images préservés)
- **Formatage inline** — les balises `<em>`, `<strong>`, `<a>`, `<sup>`, `<sub>`… survivent à la traduction via un mode « HTML node » : le LLM reçoit et retourne du HTML structuré
- **Lettrines (drop caps)** — détection et réinsertion correctes de la structure deux-spans (dropcap + corps)
- **Alinéas** — les attributs du `<body>` (dont `class` portant le `text-indent` hérité) sont restaurés après le parsing lxml

### Qualité de traduction
- **Analyse littéraire** (6 sections) : identification, cadre narratif, personnages & relations, glossaire, références culturelles, cohérence stylistique
- **Glossaire évolutif** — après chaque chapitre traduit, un appel Haiku détecte les nouveaux personnages (avec genre déduit) et termes récurrents ; l'analyse est enrichie pour les chapitres suivants
- **Contexte inter-segments** — les 3 derniers paragraphes traduits du segment précédent sont injectés pour la continuité
- **Typographie française** — tiret cadratin pour les dialogues, guillemets `«\u00a0…\u00a0»`, espaces insécables avant `;:!?»`

### Reprise et cache
- **Cache inconditionnel** — les traductions cachées sont rechargées en mémoire à chaque exécution, même sans `--resume`
- **Résumé à la demande** — `--resume` affiche le point de reprise ; `--retranslate` invalide un seul chapitre
- **Cache éditable** — `output/analysis/{book_id}_analysis.json` peut être retouché à la main avant traduction

---

## Phase 1 — Analyse

L'analyse s'exécute en 6 appels groupés sur un échantillon représentatif du livre (configurable via `sample_max_tokens`). Le résultat est un fichier JSON sauvegardé dans `output/analysis/`. Le pourcentage du livre couvert est affiché (vert ≥ 80 %, jaune ≥ 40 %, rouge < 40 %).

---

## Phase 2 — Traduction

Chaque chapitre est découpé en segments de ≤ 12 000 tokens source. Chaque segment reçoit le JSON d'analyse complet comme system prompt (mis en cache → ~10× moins cher pour les segments suivants), plus les 3 derniers paragraphes traduits du segment précédent.

Config : `config.yaml` → `translation.max_tokens_per_segment`.

---

## Reprise automatique

Si une traduction est interrompue, relancer sans argument : les chapitres déjà traduits sont rechargés depuis le cache automatiquement. Utiliser `--resume` pour afficher le message de reprise.

Le cache est stocké dans `output/cache/{book_id}/` (`state.json` + `chapter_NNNN.json`).

```bash
python -m src.main clear-cache roman.epub   # vider le cache d'un livre
```

## Retraduire un chapitre

```bash
python -m src.main translate roman.epub -r 5
```

| Format | Exemple |
|--------|---------|
| Numéro (1-based) | `-r 5` |
| Sous-titre (FR ou EN, insensible à la casse) | `-r "The Awakening"` |
| Fichier HTML | `-r chapter05.xhtml` |
| Fichier cache | `-r chapter_0004.json` |

Les autres chapitres en cache sont rechargés automatiquement.

## Table de correspondance chapitres

Avant la traduction, une table est affichée (N°, titre EN/FR, fichier HTML, fichier cache). Elle est aussi sauvegardée dans `output/cache/{book_id}/chapters.json` et mise à jour avec les titres français au fil de la traduction.

---

## Validation ePub

La commande `validate` contrôle la conformité d'un ePub et peut auto-corriger les problèmes réparables :

- Fichier `mimetype` non stocké sans compression
- Métadonnées OPF manquantes ou invalides (`dc:language`, `dc:identifier`)
- Éléments du manifeste absents
- Liens CSS ou images `src` cassés
- TOC NCX/nav incomplète ou absente

```bash
python -m src.main validate roman.epub
# ePub corrigé sauvegardé en roman_fixed.epub par défaut (ou -o pour spécifier)
```

---

## Développement — Tests

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src/
.venv/bin/mypy src/
```

---

## Structure du projet

```
epup-translator-v2/
├── pyproject.toml
├── config.yaml              # modèles, limites tokens, répertoires de sortie
├── CLAUDE.md                # instructions pour Claude Code
├── .env.example             # modèle — copier en .env et renseigner ANTHROPIC_API_KEY
├── README.md
├── CHANGELOG.md
├── src/
│   ├── main.py              # CLI (Click) : translate, clear-cache, validate
│   ├── epub_handler.py      # extraction & reconstruction ePub
│   ├── analyzer.py          # Phase 1 : analyse littéraire
│   ├── translator.py        # Phase 2 : traduction + enrichissement glossaire
│   ├── claude_client.py     # client Anthropic async (retry, cache prompt, coûts)
│   ├── prompt_builder.py    # construction des prompts d'analyse et de traduction
│   ├── models.py            # dataclasses et schémas Pydantic
│   ├── cache_manager.py     # persistance de l'état, reprise par chapitre
│   ├── epub_validator.py    # validation et correction ePub
│   └── utils.py             # chargement config YAML
├── prompts/
│   ├── analysis/            # 15 fichiers Markdown (un par section d'analyse)
│   └── translation/         # system_prompt.md + chapter_prompt.md
├── output/                  # fichiers générés (gitignored)
│   ├── cache/               # {book_id}/state.json + chapter_NNNN.json
│   └── analysis/            # {book_id}_analysis.json
└── tests/
```
