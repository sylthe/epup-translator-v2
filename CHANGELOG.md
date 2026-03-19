# Changelog

## [v1.2.0] — 2026-03-18

### Added
- **Préservation du formatage inline** (`epub_handler.py`, `translator.py`, `prompt_builder.py`) — les balises `em`, `strong`, `a`, `sup`, `sub`, `abbr`, `cite`, `code`, `s`, `u` survivent à la traduction. Quand un nœud contient du formatage inline, son inner HTML est envoyé au LLM (champ `"html"` dans le prompt) ; le LLM retourne du HTML traduit ; la réinsertion remplace les enfants du tag par le fragment parsé. `apply_french_typography()` est skippé pour ces nœuds pour ne pas corrompre les attributs HTML.
- **Glossaire évolutif** (`translator.py`) — `enrich_analysis_from_chapter()` : après chaque chapitre traduit, un appel Haiku détecte les nouveaux personnages (genre déduit depuis les pronoms) et les nouveaux termes récurrents (max 3) ; `analysis.personnages` et `analysis.glossaire` sont enrichis en place et sauvegardés via `cache.save_analysis()`. Non-fatal : retourne des listes vides en cas d'erreur.
- **Couverture de l'analyse** (`analyzer.py`) — `build_analysis_sample()` retourne désormais `(sample_text, coverage_pct)`. La couverture est affichée en couleur (vert ≥ 80 %, jaune ≥ 40 %, rouge < 40 %) lors de la phase d'analyse.
- `CLAUDE.md` — instructions pour Claude Code (architecture, commandes, conventions)

### Fixed
- **Lettrines (drop caps)** (`epub_handler.py`) — extraction : forçage de la capture au niveau `<p>` pour tous les paragraphes à lettrine, évitant la duplication du caractère initial ou la perte de structure. Réinsertion : reconstruction de la structure deux-spans (dropcap + corps) avec préservation des classes CSS.
- **Alinéas / text-indent** (`epub_handler.py`) — ebooklib/lxml strippait les attributs du `<body>` (ex. `class="class3"` qui porte `text-indent: 0.9em` hérité par tous les `<p>`). `_apply_translations()` restaure désormais le tag `<body>` original en plus du `<head>`.
- **Chargement du cache inconditionnel** (`main.py`) — les `text_nodes` traduits sont maintenant toujours rechargés depuis le cache, que `--resume` soit passé ou non. Auparavant, une 2e exécution sans `--resume` sur un livre entièrement caché produisait un epub en anglais (les chapitres étaient ignorés car déjà en cache mais leurs traductions n'étaient pas rechargées en mémoire).

---

## [v1.1.0] — 2026-03-15

### Added
- `badge-IA.png` — badge visuel apposé sur la couverture de l'epub traduit (via Pillow)
- `apply_cover_badge` dans `epub_handler.py` — détection EPUB2/EPUB3, compositing PIL
- `clear-cache` — nouvelle commande CLI pour supprimer le cache d'un livre
- `--retranslate` / `-r` — retraduire un seul chapitre sans toucher au reste du cache (accepte N°, titre, fichier HTML ou fichier cache)
- `extract_item_title()` et `classify_nonchapter_item()` dans `epub_handler.py`
- Table de correspondance chapitres affichée avant la traduction (N°, titre FR/EN, HTML, cache) et sauvegardée dans `output/cache/{book_id}/chapters.json`

### Changed
- Reconstruction ePub refactorisée en mode zipfile : copie byte-for-byte du source, seuls les fichiers HTML traduits sont remplacés (préserve CSS, polices, images)
- NCX (table des matières) : les entrées `<navLabel>` sont désormais traduites avec les titres des chapitres
- Cache restructuré par sous-répertoire : `output/cache/{book_id}/state.json` et `chapter_NNNN.json`
- Barre de progression : affiche N° chapitre, titre, fichier HTML et fichier cache en cours
- Prompt système : les dialogues utilisent systématiquement le tiret cadratin `—` (plus de `«»` pour les répliques)
- `pillow>=10.0` ajouté aux dépendances

### Fixed
- Balises `<link>` CSS perdues dans `<head>` après passage BeautifulSoup/lxml (alinéas absents)
- Correspondance clé `spine_map` : fallback par suffixe quand ebooklib retourne `chapter.xhtml` mais le zip stocke `OEBPS/chapter.xhtml`
- `ElementTree.find()` : remplacement du `or` par `is not None` (éléments XML vides sont falsy)
- `logger` non défini dans `epub_handler.py`
- `chapter_info` → `chapter` dans le label de progression des segments (`translator.py`)
- Détection de titre de chapitre via xpath pour les cas `<h2><em>…</em></h2>`
- **Préservation des polices dans l'ePub traduit** — trois corrections dans `epub_handler.py` :
  - `_has_adjacent_span_children()` : détecte les spans directement adjacents (word-split Calibre) et capture le `<p>` parent comme un seul nœud — l'IA reçoit la phrase complète au lieu de fragments (`"What is g"` / `"oing on with me"`)
  - `_dominant_span_class()` + `_apply_translations` (cas nœud unique) : quand un `<p>` est remplacé, enveloppe le texte traduit dans un `<span class="…">` dominant — préserve les surcharges de police CSS (ex. Times New Roman 1.33em via `c5` vs Calibri 1em via `western4`)
  - `_apply_translations` (cas block-split) : applique la même logique pour les nouveaux `<p>` créés lors de la découpe en lignes (dialogues avec incises)

---

## [v1.0.0] — 2026-03-11

### Added
- `src/translator.py` — Phase 2 translation: segment splitting, inter-segment context, per-chapter caching
- `src/main.py` — Click CLI: `translate` command with `--output`, `--analysis-only`, `--resume`, `--skip-analysis`
- `src/utils.py` — YAML config loader
- `.github/workflows/ci.yml` — CI: pytest + ruff + mypy on Python 3.11 and 3.12
- `tests/conftest.py` — shared test fixtures
- `tests/test_integration.py` — full pipeline integration tests
- 41 tests total, all passing

## [v0.2.0] — 2026-03-11

### Added
- `prompts/analysis/` — 15 Markdown analysis prompt files
- `prompts/translation/` — system_prompt.md and chapter_prompt.md
- `src/prompt_builder.py` — PromptBuilder with ANALYSIS_SECTIONS constant
- `src/analyzer.py` — Phase 1 analysis (6 sequential API calls), JSON parsing, Rich summary table
- `--analysis-only` mode is now functionally complete
- 9 additional tests for analyzer module

## [v0.1.0] — 2026-03-11

### Added
- `src/models.py` — all dataclasses and Pydantic schemas
- `src/epub_handler.py` — ePub extraction and reconstruction
- `src/claude_client.py` — async Anthropic client with retry and cost tracking
- `src/cache_manager.py` — translation state persistence and chapter-level resume
- Full project scaffold: `pyproject.toml`, `config.yaml`, module stubs, directory structure
- 15 passing tests across epub_handler and cache_manager
