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
4. **Reconstruction** — translated text is reinjected into the original HTML tree and a new ePub is written

---

## Installation

```bash
pip install -e .
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

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

If a translation is interrupted, re-run with `--resume`. The cache manager (`src/cache_manager.py`) stores state in `output/cache/{book_id}_state.json` and restarts from the last completed chapter.

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
