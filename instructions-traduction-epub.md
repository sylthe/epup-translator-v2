# Instructions pour Claude Code — Application de traduction de romans ePub (EN→FR)

## Contexte du projet

Je veux une application Python autonome qui traduit des romans au format `.epub` de l'anglais au français, en conservant intégralement la mise en page du fichier original. L'application doit reproduire le processus d'un traducteur professionnel : **d'abord analyser l'œuvre selon une grille complète, puis traduire en s'appuyant sur cette analyse.**

L'application fait appel à l'API Claude d'Anthropic (modèle `claude-sonnet-4-20250514`) pour l'analyse et la traduction.

---

## Architecture : Pipeline orchestré en phases

L'application suit un pipeline séquentiel en **3 phases principales**, orchestré par un script Python central. Ce n'est pas un framework agentique avec boucles autonomes — c'est un pipeline déterministe où chaque phase produit un artefact JSON/YAML qui alimente la suivante.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐
│  EXTRACTION  │ ──▶ │  PHASE 1 : ANALYSE│ ──▶ │ PHASE 2 : TRAD. │ ──▶ │ RECONSTRUCTION│
│  ePub → HTML │     │  Grille complète  │     │  Chapitre/chapitre│    │  HTML → ePub  │
└─────────────┘     └──────────────────┘     └─────────────────┘     └──────────────┘
```

### Pourquoi cette architecture plutôt qu'un agent autonome

- **Reproductibilité** : chaque phase produit un fichier intermédiaire vérifiable.
- **Reprise sur erreur** : si la traduction plante au chapitre 12, on reprend au chapitre 12 sans tout refaire.
- **Contrôle des coûts** : on sait exactement combien de tokens chaque phase consomme.
- **Qualité** : le contexte d'analyse est injecté dans chaque prompt de traduction, garantissant la cohérence.

---

## Structure du projet

```
epub-translator/
├── pyproject.toml              # Dépendances et config du projet
├── README.md
├── config.yaml                 # Configuration (modèle, clé API, etc.)
├── src/
│   ├── __init__.py
│   ├── main.py                 # Point d'entrée CLI principal
│   ├── epub_handler.py         # Extraction et reconstruction ePub
│   ├── analyzer.py             # Phase 1 : Analyse via Claude
│   ├── translator.py           # Phase 2 : Traduction via Claude
│   ├── claude_client.py        # Client API Anthropic (wrapper)
│   ├── prompt_builder.py       # Construction des prompts
│   ├── models.py               # Dataclasses / Pydantic models
│   ├── cache_manager.py        # Gestion du cache et reprise
│   └── utils.py                # Utilitaires divers
├── prompts/
│   ├── analysis/
│   │   ├── 01_identification.md
│   │   ├── 02_cadre_narratif.md
│   │   ├── 03_ton_style.md
│   │   ├── 04_personnages.md
│   │   ├── 05_relations.md
│   │   ├── 06_registre_dialogues.md
│   │   ├── 07_glossaire.md
│   │   ├── 08_idiomes.md
│   │   ├── 09_references_culturelles.md
│   │   ├── 10_structure_texte.md
│   │   ├── 11_contraintes_grammaticales.md
│   │   ├── 12_coherence_stylistique.md
│   │   ├── 13_themes.md
│   │   ├── 14_sensibilite_contenu.md
│   │   └── 15_notes_traduction.md
│   └── translation/
│       ├── system_prompt.md
│       └── chapter_prompt.md
├── output/                     # Fichiers de sortie
│   ├── analysis/               # Résultats d'analyse (JSON)
│   └── translated/             # ePub traduits
└── tests/
    ├── test_epub_handler.py
    ├── test_analyzer.py
    └── test_translator.py
```

---

## Dépendances Python

```toml
[project]
name = "epub-translator"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",       # SDK officiel Anthropic
    "ebooklib>=0.18",          # Lecture/écriture ePub
    "beautifulsoup4>=4.12",    # Parsing HTML des chapitres
    "lxml>=5.0",               # Parser HTML rapide
    "pyyaml>=6.0",             # Configuration
    "pydantic>=2.0",           # Validation des modèles de données
    "rich>=13.0",              # Affichage console (progression)
    "click>=8.0",              # Interface CLI
    "tiktoken>=0.7",           # Comptage de tokens
]
```

---

## Phase 0 : Extraction ePub

### Fichier : `epub_handler.py`

Le module doit :

1. **Ouvrir le fichier ePub** avec `ebooklib`.
2. **Extraire tous les documents XHTML/HTML** dans l'ordre du spine (table des matières).
3. **Séparer le contenu textuel de la structure HTML** avec BeautifulSoup :
   - Conserver l'arbre HTML complet de chaque fichier (balises, classes CSS, attributs, images).
   - Extraire uniquement le texte des nœuds textuels pour l'envoyer à Claude.
4. **Préserver intégralement** : CSS, images, polices, metadata OPF, fichier `toc.ncx` / `nav.xhtml`.
5. **Produire une structure de données** :

```python
@dataclass
class EpubContent:
    metadata: dict                    # Titre, auteur, langue, etc.
    spine_items: list[SpineItem]      # Ordre de lecture
    styles: list[StyleSheet]          # CSS
    images: list[Image]               # Images embarquées
    fonts: list[Font]                 # Polices embarquées
    toc: list[TocEntry]              # Table des matières
    raw_book: ebooklib.epub.EpubBook  # Référence au livre original

@dataclass
class SpineItem:
    id: str                          # ID dans le spine
    filename: str                    # ex: "chapter01.xhtml"
    html_tree: BeautifulSoup         # Arbre HTML complet
    text_nodes: list[TextNode]       # Nœuds textuels extraits
    is_chapter: bool                 # True si c'est un chapitre narratif
    chapter_number: int | None       # Numéro de chapitre si applicable

@dataclass
class TextNode:
    xpath: str                       # Chemin vers le nœud dans le HTML
    original_text: str               # Texte anglais original
    translated_text: str | None      # Sera rempli par la traduction
    parent_tag: str                  # ex: "p", "h1", "span"
    attributes: dict                 # Classes CSS, etc.
```

### Stratégie clé pour préserver la mise en page

**Ne jamais modifier l'arbre HTML directement.** À la place :
- Extraire les nœuds textuels avec leur chemin (xpath ou index).
- Envoyer uniquement le texte à Claude.
- Réinjecter le texte traduit aux mêmes emplacements.
- L'arbre HTML, le CSS, les images restent intacts.

---

## Phase 1 : Analyse du roman (Grille professionnelle)

### Fichier : `analyzer.py`

L'analyse se fait en **plusieurs appels API séquentiels**, chacun correspondant à une section de la grille. On envoie un échantillon représentatif du texte (premiers chapitres + passages clés) plutôt que le roman entier pour l'analyse.

### Stratégie d'échantillonnage

```python
def build_analysis_sample(spine_items: list[SpineItem]) -> str:
    """
    Construit un échantillon représentatif pour l'analyse.
    - Chapitres 1 à 3 en entier (établir le ton, les personnages, le style)
    - Un chapitre du milieu (vérifier la cohérence)
    - Le dernier chapitre (vérifier l'évolution)
    - Total visé : ~50 000 tokens max pour l'échantillon
    """
```

### Séquence d'appels API pour l'analyse

Chaque appel API reçoit l'échantillon + un prompt spécifique à la section de la grille. Les résultats sont structurés en JSON.

```python
ANALYSIS_SECTIONS = [
    # Groupe 1 : Identification et structure (1 appel)
    {
        "name": "identification_et_structure",
        "sections": [1, 10],  # Identification + Structure du texte
        "prompt_file": "01_identification.md",
    },
    # Groupe 2 : Narratologie (1 appel)
    {
        "name": "cadre_narratif_et_style",
        "sections": [2, 3],  # Cadre narratif + Ton et style
        "prompt_file": "02_cadre_narratif.md",
    },
    # Groupe 3 : Personnages (1 appel, peut être le plus long)
    {
        "name": "personnages_et_relations",
        "sections": [4, 5, 6],  # Personnages + Relations + Registre dialogues
        "prompt_file": "04_personnages.md",
    },
    # Groupe 4 : Linguistique (1 appel)
    {
        "name": "linguistique",
        "sections": [7, 8, 11],  # Glossaire + Idiomes + Contraintes grammaticales
        "prompt_file": "07_glossaire.md",
    },
    # Groupe 5 : Culture et thèmes (1 appel)
    {
        "name": "culture_themes_sensibilite",
        "sections": [9, 13, 14],  # Références culturelles + Thèmes + Sensibilité
        "prompt_file": "09_references_culturelles.md",
    },
    # Groupe 6 : Cohérence et notes finales (1 appel)
    {
        "name": "coherence_et_notes",
        "sections": [12, 15],  # Cohérence stylistique + Notes de traduction
        "prompt_file": "12_coherence_stylistique.md",
    },
]
```

### Format de sortie de l'analyse

L'analyse complète est sauvegardée dans un fichier JSON structuré :

```json
{
  "book_id": "sha256_du_epub",
  "analysis_date": "2025-01-15T10:30:00",
  "identification": {
    "titre_original": "...",
    "auteur": "...",
    "annee": 2023,
    "genre": "Romance",
    "sous_genre": "M/M Contemporary",
    "public_cible": "Adulte",
    "nb_chapitres": 28,
    "nb_mots_estime": 85000
  },
  "cadre_narratif": {
    "point_de_vue": "1re personne",
    "narrateur": "alternance (2 personnages)",
    "temps_narratif": "passé",
    "alternance_pov": true,
    "distance_narrative": "interne",
    "monologue_interieur": true,
    "style_indirect_libre": true
  },
  "ton_style": {
    "niveau_langue": "familier-standard",
    "ton": "humoristique avec moments dramatiques",
    "style": "descriptif, dialogues abondants",
    "longueur_phrases": "courte à moyenne",
    "rythme": "rapide",
    "repetitions_stylistiques": ["..."],
    "metaphores_recurrentes": ["..."],
    "figures_de_style": ["..."]
  },
  "personnages": [
    {
      "nom": "Liam",
      "genre": "masculin",
      "age": "28 ans",
      "role_narratif": "protagoniste / narrateur POV 1",
      "personnalite": "sarcastique, vulnérable sous la surface",
      "style_parole": "phrases courtes, sarcasme, humour défensif",
      "particularites_linguistiques": [
        "utilise 'damn' et 'shit' fréquemment",
        "sarcasme comme mécanisme de défense",
        "vocabulaire de pompier (jargon professionnel)"
      ]
    }
  ],
  "relations": [
    {
      "personnages": ["Liam", "Jake"],
      "relation": "amoureux (tension → couple)",
      "registre": "tu",
      "termes_affectifs": ["babe", "sweetheart (ironique)"],
      "surnoms": ["Li"]
    }
  ],
  "registre_dialogues": {
    "langage_familier": true,
    "argot": "fréquent",
    "humour": "sarcasme + ironie",
    "interjections": "fréquentes",
    "table_traduction": {
      "yeah": "ouais",
      "damn": "merde",
      "shit": "putain",
      "dude": "mec",
      "babe": "bébé / mon cœur",
      "whatever": "peu importe / m'en fous"
    }
  },
  "glossaire": {
    "termes": [
      {"en": "firehouse", "fr": "caserne", "contexte": "lieu de travail de Liam"},
      {"en": "turnout gear", "fr": "tenue d'intervention", "contexte": "équipement pompier"}
    ]
  },
  "idiomes": [
    {"expression": "give it a shot", "sens": "essayer", "traduction": "tenter le coup"},
    {"expression": "lose it", "sens": "perdre le contrôle", "traduction": "péter un câble"}
  ],
  "references_culturelles": [
    {"element": "Thanksgiving", "type": "fête", "decision": "conserver"},
    {"element": "SAT", "type": "système scolaire", "decision": "adapter → examens d'entrée"}
  ],
  "structure_texte": {
    "chapitres_titres": true,
    "lettres": false,
    "sms": true,
    "journaux_intimes": false,
    "extraits_livres": false,
    "notes_adaptation": "Les SMS doivent conserver un style texto français (stp, pk, etc.)"
  },
  "contraintes_grammaticales": [
    {"type": "ambiguïté de genre", "exemple": "they/them pour personnage non-binaire", "strategie": "utiliser 'iel' ou reformuler"},
    {"type": "phrasal verbs", "exemple": "look up / look after", "strategie": "toujours contextualiser"}
  ],
  "coherence_stylistique": {
    "expressions_recurrentes": [
      {"en": "He felt the knot in his chest tighten", "fr": "Il sentit le nœud dans sa poitrine se resserrer"}
    ],
    "metaphores": ["..."],
    "phrases_signature": ["..."]
  },
  "themes": [
    {"theme": "amour", "importance": "majeur"},
    {"theme": "identité", "importance": "secondaire"},
    {"theme": "rédemption", "importance": "majeur"}
  ],
  "sensibilite_contenu": {
    "scenes_sexuelles": true,
    "violence": false,
    "humour_noir": true,
    "notes": "Scènes intimes explicites — maintenir un vocabulaire sensuel mais pas clinique"
  },
  "notes_traduction": [
    "Liam utilise beaucoup de sarcasme → privilégier des phrases courtes et mordantes",
    "Le tutoiement entre Liam et Jake commence au chapitre 8",
    "Conserver les noms propres anglais sans les franciser",
    "Les références à la culture américaine (football, Thanksgiving) sont conservées avec notes implicites quand nécessaire"
  ]
}
```

---

## Phase 2 : Traduction chapitre par chapitre

### Fichier : `translator.py`

Chaque chapitre est traduit individuellement. Le **contexte d'analyse complet** est injecté dans le system prompt de chaque appel.

### System prompt de traduction

Le system prompt (fichier `prompts/translation/system_prompt.md`) doit contenir :

```markdown
Tu es un traducteur littéraire professionnel spécialisé dans la traduction
de romans de l'anglais vers le français. Tu traduis avec précision tout en
préservant le style, le ton et la voix de l'auteur.

## Analyse du roman

Voici l'analyse complète du roman que tu traduis. Tu DOIS respecter
rigoureusement ces consignes dans chaque chapitre :

{analysis_json}

## Règles de traduction

1. **Fidélité au ton** : Respecte le niveau de langue identifié dans l'analyse.
2. **Cohérence des personnages** : Chaque personnage a un style de parole défini.
   Reporte-toi à la fiche de chaque personnage.
3. **Glossaire** : Utilise TOUJOURS les traductions du glossaire pour les termes
   techniques et récurrents.
4. **Tutoiement/Vouvoiement** : Respecte strictement le tableau des relations.
5. **Idiomes** : Utilise les traductions validées dans la table des idiomes.
   Ne traduis JAMAIS littéralement une expression idiomatique.
6. **Références culturelles** : Applique les décisions (conserver/adapter)
   de l'analyse.
7. **Cohérence stylistique** : Les expressions récurrentes et métaphores
   doivent être traduites de façon identique à chaque occurrence.
8. **Format** : Tu reçois le texte structuré par nœuds. Traduis CHAQUE nœud
   individuellement. Ne fusionne pas et ne divise pas les nœuds.
9. **Contenu sensible** : Ne censure rien. Traduis fidèlement le contenu
   tel qu'il est, y compris les scènes explicites et le langage cru.

## Format de réponse

Tu DOIS répondre en JSON valide selon ce format exact :

```json
{
  "translated_nodes": [
    {
      "index": 0,
      "original": "texte anglais",
      "translated": "texte français"
    }
  ],
  "translation_notes": [
    "Note sur un choix de traduction particulier"
  ]
}
```
```

### Prompt par chapitre

```markdown
Traduis le chapitre {chapter_number} : "{chapter_title}"

Contexte narratif :
- Ce chapitre est narré du point de vue de : {pov_character}
- Personnages présents : {characters_in_chapter}
- Événements précédents (résumé) : {previous_summary}

Voici les nœuds textuels à traduire :

{text_nodes_json}
```

### Gestion de la taille des chapitres

Les chapitres longs doivent être découpés en segments pour respecter la fenêtre de contexte :

```python
MAX_TOKENS_PER_REQUEST = 16000  # Tokens de texte source par requête
# (garder de la marge pour le system prompt + analyse + réponse)

def split_chapter_into_segments(
    text_nodes: list[TextNode],
    max_tokens: int = MAX_TOKENS_PER_REQUEST
) -> list[list[TextNode]]:
    """
    Découpe les nœuds d'un chapitre en segments traduisibles.
    Coupe de préférence entre les paragraphes, jamais au milieu d'un dialogue.
    """
```

### Gestion de la cohérence inter-segments

Quand un chapitre est découpé, chaque segment après le premier reçoit en contexte additionnel :
- Les 3 derniers paragraphes traduits du segment précédent (pour la continuité).
- Un rappel des personnages en scène.

---

## Phase 3 : Reconstruction du ePub

### Fichier : `epub_handler.py` (méthode de reconstruction)

1. **Réinjection du texte traduit** dans l'arbre HTML de chaque `SpineItem`, nœud par nœud.
2. **Mise à jour des métadonnées** :
   - `dc:language` → `fr`
   - `dc:title` → titre traduit (si applicable)
   - Ajout d'un champ `dc:contributor` avec "Traduit par IA (Claude)"
3. **Reconstruction du ePub** avec `ebooklib`, en conservant :
   - Tous les fichiers CSS originaux
   - Toutes les images
   - Toutes les polices
   - La structure du spine
   - La table des matières (traduite)
4. **Validation** du ePub résultant avec `epubcheck` si disponible.

---

## Fonctionnalités essentielles

### 1. Cache et reprise (`cache_manager.py`)

```python
class CacheManager:
    """
    Gère la persistance de l'état de traduction.
    Sauvegarde après chaque chapitre traduit.
    Permet de reprendre une traduction interrompue.
    """
    def __init__(self, book_id: str, cache_dir: Path):
        self.state_file = cache_dir / f"{book_id}_state.json"

    def save_chapter_result(self, chapter_num: int, result: TranslationResult):
        """Sauvegarde le résultat de traduction d'un chapitre."""

    def get_last_completed_chapter(self) -> int:
        """Retourne le dernier chapitre complété pour la reprise."""

    def is_analysis_complete(self) -> bool:
        """Vérifie si l'analyse est déjà faite."""
```

### 2. Interface CLI (`main.py`)

```python
@click.group()
def cli():
    """Traducteur de romans ePub EN→FR avec analyse professionnelle."""

@cli.command()
@click.argument('epub_path', type=click.Path(exists=True))
@click.option('--output', '-o', help='Chemin du fichier ePub traduit')
@click.option('--analysis-only', is_flag=True, help='Exécuter seulement l\'analyse')
@click.option('--resume', is_flag=True, help='Reprendre une traduction interrompue')
@click.option('--skip-analysis', is_flag=True, help='Utiliser une analyse existante')
def translate(epub_path, output, analysis_only, resume, skip_analysis):
    """Traduit un roman ePub de l'anglais au français."""
```

### 3. Affichage de progression (`rich`)

```python
# Utiliser rich pour afficher la progression en temps réel :
# - Barre de progression globale (chapitres)
# - Barre de progression par chapitre (segments)
# - Estimation du coût API (tokens consommés)
# - Temps estimé restant
```

### 4. Gestion des erreurs et retry

```python
# Retry automatique avec backoff exponentiel pour :
# - Erreurs réseau (timeout, connection reset)
# - Rate limiting (429)
# - Erreurs serveur (500, 502, 503)
# Maximum 3 retries par requête.
# Si échec persistant, sauvegarder l'état et proposer la reprise.
```

---

## Configuration (`config.yaml`)

```yaml
api:
  model: "claude-sonnet-4-20250514"
  max_tokens_response: 8192
  temperature: 0.3          # Bas pour la cohérence de traduction

translation:
  max_tokens_per_segment: 16000
  overlap_paragraphs: 3     # Paragraphes de contexte entre segments
  batch_delay_seconds: 1    # Délai entre appels API

analysis:
  sample_chapters: [1, 2, 3]  # Chapitres analysés en entier
  include_middle: true         # Ajouter un chapitre du milieu
  include_last: true           # Ajouter le dernier chapitre

output:
  cache_dir: "./output/cache"
  analysis_dir: "./output/analysis"
  translated_dir: "./output/translated"
```

---

## Prompts d'analyse détaillés

Chaque fichier dans `prompts/analysis/` contient un prompt structuré. Voici le modèle pour le premier :

### `prompts/analysis/01_identification.md`

```markdown
Analyse le texte suivant et fournis les informations d'identification et de structure.

Réponds UNIQUEMENT en JSON valide selon ce schéma :

{
  "identification": {
    "titre_original": "string",
    "auteur": "string",
    "annee_publication": "int ou null",
    "genre": "string",
    "sous_genre": "string",
    "public_cible": "string",
    "nb_chapitres": "int",
    "nb_mots_estime": "int"
  },
  "structure_texte": {
    "chapitres_titres": "bool",
    "presence_lettres": "bool",
    "presence_sms": "bool",
    "presence_journaux_intimes": "bool",
    "presence_extraits_livres": "bool",
    "formats_speciaux": ["description de chaque format spécial détecté"],
    "notes_adaptation_typographique": "string"
  }
}

TEXTE À ANALYSER :
{sample_text}
```

### `prompts/analysis/04_personnages.md`

```markdown
Analyse les personnages, leurs relations et le registre des dialogues.

Réponds UNIQUEMENT en JSON valide selon ce schéma :

{
  "personnages": [
    {
      "nom": "string",
      "genre": "string",
      "age": "string",
      "role_narratif": "string (protagoniste/antagoniste/secondaire)",
      "personnalite": "string (description concise)",
      "style_parole": "string",
      "particularites_linguistiques": ["string"],
      "exemples_dialogue": [
        {"en": "citation originale", "fr_suggere": "traduction suggérée"}
      ]
    }
  ],
  "relations": [
    {
      "personnages": ["Nom A", "Nom B"],
      "relation": "string",
      "registre": "tu ou vous",
      "evolution_registre": "string ou null (ex: 'vous → tu à partir du chapitre 8')",
      "termes_affectifs": ["string"],
      "surnoms": ["string"]
    }
  ],
  "registre_dialogues": {
    "langage_familier": "bool",
    "niveau_argot": "léger / modéré / fréquent",
    "type_humour": "string",
    "frequence_interjections": "rares / occasionnelles / fréquentes",
    "table_traduction_expressions": {
      "expression_en": "traduction_fr"
    }
  }
}

TEXTE À ANALYSER :
{sample_text}
```

Crée les autres fichiers de prompts sur le même modèle pour chaque groupe d'analyse.

---

## Flux d'exécution complet

```python
async def run_translation(epub_path: str, config: Config) -> str:
    """Flux principal de traduction."""

    # 0. Extraction
    console.print("[bold]Phase 0 : Extraction du ePub[/bold]")
    epub_content = extract_epub(epub_path)

    # 1. Analyse (ou chargement depuis le cache)
    cache = CacheManager(epub_content.book_id, config.cache_dir)

    if cache.is_analysis_complete():
        console.print("Analyse trouvée dans le cache, chargement...")
        analysis = cache.load_analysis()
    else:
        console.print("[bold]Phase 1 : Analyse du roman[/bold]")
        sample = build_analysis_sample(epub_content.spine_items)
        analysis = await run_analysis(sample, epub_content.metadata, config)
        cache.save_analysis(analysis)

        # Afficher un résumé de l'analyse pour validation humaine
        display_analysis_summary(analysis)
        if not click.confirm("L'analyse est-elle satisfaisante ?"):
            console.print("Vous pouvez modifier le fichier d'analyse et relancer avec --skip-analysis")
            return

    # 2. Traduction chapitre par chapitre
    console.print("[bold]Phase 2 : Traduction[/bold]")
    start_chapter = cache.get_last_completed_chapter() + 1

    chapters = [item for item in epub_content.spine_items if item.is_chapter]
    with Progress() as progress:
        task = progress.add_task("Traduction", total=len(chapters))

        for chapter in chapters[start_chapter:]:
            segments = split_chapter_into_segments(chapter.text_nodes)

            for segment_idx, segment in enumerate(segments):
                result = await translate_segment(
                    segment=segment,
                    analysis=analysis,
                    chapter_info=chapter,
                    segment_context=get_segment_context(segment_idx, segments),
                    config=config
                )

                apply_translations(chapter, result)

            cache.save_chapter_result(chapter.chapter_number, chapter)
            progress.advance(task)

    # 3. Reconstruction
    console.print("[bold]Phase 3 : Reconstruction du ePub[/bold]")
    output_path = reconstruct_epub(epub_content, config.output_path)

    console.print(f"[green bold]Traduction terminée : {output_path}[/green bold]")
    return output_path
```

---

## Commande d'exécution

```bash
# Traduction complète
python -m src.main translate mon_roman.epub -o mon_roman_fr.epub

# Analyse seule (pour vérification avant traduction)
python -m src.main translate mon_roman.epub --analysis-only

# Reprendre une traduction interrompue
python -m src.main translate mon_roman.epub --resume

# Utiliser une analyse modifiée manuellement
python -m src.main translate mon_roman.epub --skip-analysis
```

---

## Points d'attention pour Claude Code

1. **Commence par créer les modèles Pydantic** (`models.py`) — ils définissent le contrat de données entre toutes les phases.
2. **Teste l'extraction ePub en premier** — c'est le fondement. Utilise un petit ePub de test.
3. **Les prompts sont des fichiers Markdown séparés** — pas des strings hardcodées dans le code. Ça permet de les itérer facilement.
4. **Chaque appel API doit demander du JSON structuré** — utilise le paramètre `response_format` ou une instruction claire dans le prompt.
5. **Le cache est critique** — un roman de 80 000 mots peut nécessiter 30+ appels API. Sans cache, une erreur au chapitre 25 = tout recommencer.
6. **Utilise `asyncio` et le client Anthropic async** pour la performance, mais **ne parallélise PAS les chapitres** — la traduction doit être séquentielle pour maintenir la cohérence narrative.
7. **Compte les tokens** avec `tiktoken` avant chaque appel pour éviter de dépasser les limites.
8. **Validation humaine** : après l'analyse, affiche un résumé et demande confirmation avant de lancer la traduction (qui est coûteuse en tokens).

---

## Estimation des coûts (à titre indicatif)

Pour un roman de 80 000 mots (~100 000 tokens) :
- **Phase 1 (Analyse)** : ~6 appels × ~60K tokens input = ~360K tokens input, ~30K output
- **Phase 2 (Traduction)** : ~25-30 segments × ~25K tokens input (texte + analyse + contexte) = ~750K tokens input, ~400K output
- **Total estimé** : ~1.1M tokens input, ~430K tokens output

Consulte la page de tarification Anthropic pour le coût actuel du modèle choisi.
