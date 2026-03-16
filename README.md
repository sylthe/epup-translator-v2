# epub-translator

A Python CLI application that translates English `.epub` novels to French using Claude AI (`claude-sonnet-4-20250514`). It mimics a professional translator workflow: first a comprehensive literary analysis, then chapter-by-chapter translation guided by that analysis.

---

## Pipeline

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐
│  EXTRACTION  │ ──▶ │  PHASE 1 : ANALYSE│ ──▶ │ PHASE 2 : TRAD. │ ──▶ │ RECONSTRUCTION│
│  ePub → HTML │     │  Grille complète  │     │  Chapitre/chapitre│   │  HTML → ePub  │
└─────────────┘     └──────────────────┘     └─────────────────┘     └──────────────┘
```

1. **Extraction** — parse the ePub, isolate text nodes while preserving the HTML tree
2. **Analysis (Phase 1)** — 6 sequential API calls build a structured JSON profile (characters, tone, glossary, cultural references, …)
3. **Translation (Phase 2)** — each chapter is split into segments, translated with the analysis injected as context
4. **Reconstruction** — translated text is reinjected into the original HTML tree and a new ePub is written; a badge "IA" is composited onto the cover if `badge-IA.png` is present

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

> **Alternative** : exporter la variable directement dans le shell — elle prend la priorité sur `.env`.
> ```bash
> export ANTHROPIC_API_KEY="sk-ant-..."
> ```

---

## Usage

```bash
# Full translation
python -m src.main translate roman.epub -o roman_fr.epub

# Analysis only (review before committing to translation)
python -m src.main translate roman.epub --analysis-only

# Resume an interrupted translation
python -m src.main translate roman.epub --resume

# Use an existing (possibly hand-edited) analysis
python -m src.main translate roman.epub --skip-analysis

# Retranslate a specific chapter (accepts number, title, HTML file, or cache file)
python -m src.main translate roman.epub -r 5
python -m src.main translate roman.epub -r "The Awakening"
python -m src.main translate roman.epub -r chapter05.xhtml
python -m src.main translate roman.epub -r chapter_0004.json

# Clear the cache for a book
python -m src.main clear-cache roman.epub

# Validate and auto-correct an ePub (saves corrected file alongside the source)
python -m src.main validate roman.epub
python -m src.main validate roman.epub --no-fix        # report only, no correction
python -m src.main validate roman.epub -o corrected.epub
```

---

## Data Models

See `src/models.py` — full schema documentation in the `feature/data-models` PR.

---

## Prompts

Analysis prompts live in `prompts/analysis/` (15 Markdown files, one per analysis section).
Translation prompts live in `prompts/translation/`.

---

## Phase 1 — Analysis

The analysis runs as 6 grouped API calls against a representative sample of the book (~50 000 tokens). The result is a structured JSON file saved to `output/analysis/`.

---

## Phase 2 — Translation

Each chapter is split into segments of ≤16 000 source tokens. Each segment receives the full analysis JSON as context, plus the last 3 translated paragraphs of the previous segment for continuity.

Config: `config.yaml` → `translation.max_tokens_per_segment`.

---

## Automatic resume

If a translation is interrupted, re-run with `--resume`. The cache manager (`src/cache_manager.py`) stores state in `output/cache/{book_id}/state.json` and chapter results in `output/cache/{book_id}/chapter_NNNN.json`. Restarts from the last completed chapter.

To clear the cache for a specific book:

```bash
python -m src.main clear-cache roman.epub
```

## Retranslating a chapter

To retranslate a single chapter without touching the rest of the cache, use `--retranslate` / `-r`. The identifier can be any of:

| Format | Example |
|--------|---------|
| Chapter number (1-based) | `-r 5` |
| Title substring (FR or EN, case-insensitive) | `-r "The Awakening"` |
| HTML filename | `-r chapter05.xhtml` |
| Cache filename | `-r chapter_0004.json` |

The other cached chapters are loaded automatically so the reconstructed ePub remains complete.

## Chapter correspondence table

Before translation begins, a table is displayed mapping each spine item to its chapter number, title, HTML file, and cache file. The table is also saved to `output/cache/{book_id}/chapters.json` and updated with French titles as chapters are translated.

---

## ePub validation

The `validate` command checks an ePub for conformance issues and can auto-correct fixable ones:

- `mimetype` file not stored uncompressed
- Missing or invalid `dc:language` / `dc:identifier` OPF metadata
- Manifest items referenced in spine but absent from manifest
- Broken CSS `<link>` or image `src` references
- Incomplete or missing NCX/nav TOC

```bash
python -m src.main validate roman.epub
# Corrected ePub saved as roman_fixed.epub by default (or use -o to specify path)
```

---

## Development — Run the tests

```bash
pytest tests/
ruff check src/
mypy src/
```

---

## Project structure

```
epub-translator/
├── pyproject.toml
├── config.yaml
├── .env.example         # modèle — copier en .env et renseigner ANTHROPIC_API_KEY
├── README.md
├── src/
│   ├── main.py          # CLI entry point
│   ├── epub_handler.py  # ePub extraction & reconstruction
│   ├── analyzer.py      # Phase 1 analysis
│   ├── translator.py    # Phase 2 translation
│   ├── claude_client.py # Anthropic API wrapper
│   ├── prompt_builder.py
│   ├── models.py
│   ├── cache_manager.py
│   └── utils.py
├── prompts/
│   ├── analysis/        # 15 analysis prompt files
│   └── translation/     # system_prompt.md + chapter_prompt.md
├── output/              # generated files (gitignored)
└── tests/
```
