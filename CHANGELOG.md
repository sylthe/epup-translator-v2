# Changelog

## [Unreleased / develop]

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
