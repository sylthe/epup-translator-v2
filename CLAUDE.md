# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Langue

Toujours répondre en français, quelle que soit la langue utilisée par l'utilisateur.

## Commands

```bash
# Always use the .venv interpreter (system python3 is x86_64, incompatible)
.venv/bin/python -m pytest tests/              # run all tests
.venv/bin/python -m pytest tests/test_epub_handler.py -k test_extract  # single test
.venv/bin/python -m pytest tests/ -q           # quiet output

.venv/bin/ruff check src/
.venv/bin/mypy src/

# Run the CLI
.venv/bin/python -m src.main translate roman.epub -o roman_fr.epub
.venv/bin/python -m src.main translate roman.epub -r 5   # retranslate chapter 5
.venv/bin/python -m src.main clear-cache roman.epub
.venv/bin/python -m src.main validate roman.epub
```

## Architecture

### Pipeline (linear, phases in order)

```
extract_epub()  →  run_analysis()  →  translate_chapter() × N  →  reconstruct_epub()  →  apply_cover_badge()
epub_handler       analyzer            translator                   epub_handler           epub_handler
```

**Phase 1 (Analysis)** — `src/analyzer.py`: 6 sequential API calls against a sample of the book, each answering a different prompt file from `prompts/analysis/`. Produces a single `AnalysisResult` (Pydantic) saved to `output/analysis/{book_id}_analysis.json`. Uses `claude-haiku` (cheap, fast).

**Phase 2 (Translation)** — `src/translator.py`: each chapter's `TextNode` list is split into segments (≤12 000 source tokens). Each segment call injects the full analysis JSON as a cached system prompt, plus 3 overlap paragraphs from the previous segment. Uses `claude-sonnet`. Responses are validated with `json-repair`; untranslated nodes trigger a retry. `apply_french_typography()` post-processes every node.

### Text node extraction and reinjection (`src/epub_handler.py`)

`_extract_text_nodes()` walks the BS4 tree and builds `TextNode` objects, each with an XPath-like address (`body/div[2]/p[1]/span[3]`). Key rules:
- A tag is captured whole if it has non-whitespace `NavigableString` children (e.g. `<p>"<span>text</span></p>` → captured at `<p>` level).
- Adjacent `<span>` children with **no NavigableString between them** (word-split Calibre artifact) also force capture at parent level via `_has_adjacent_span_children()`.
- Otherwise the walker recurses and captures each `<span>` individually.

`_apply_translations()` reinserts text by xpath. For block elements:
- Single-line replacement: finds the dominant span class via `_dominant_span_class()`, wraps translated text in `<span class="…">` to preserve CSS font overrides.
- Multi-line (dialogue + narrative break via `\n`): splits into sibling `<p>` elements, each also wrapped with the dominant span class.

Reconstruction (`reconstruct_epub`) copies the source zip byte-for-byte, replacing only translated HTML files. This preserves all CSS/fonts/images. The `<head>` is restored from the original after BS4 processing to prevent CSS link loss.

### Data flow for resume

`CacheManager` (keyed by `book_id = title-slug + 8-char SHA256`) writes atomically:
- `output/cache/{book_id}/state.json` — completed chapter list
- `output/cache/{book_id}/chapter_{NNNN}.json` — serialised `TextNode` list with `translated_text`
- `output/analysis/{book_id}_analysis.json` — editable `AnalysisResult`

On resume, cached `TextNode` lists overwrite the freshly extracted ones. The `--retranslate/-r` flag calls `cache.invalidate_chapter()` then forces resume semantics so all other chapters are still loaded from cache.

### Prompt caching (cost)

The system prompt (analysis JSON, ~25 000 tokens) is marked `cache_control: ephemeral` on the first segment call. Subsequent segments within the same run pay cache-read rates (~10× cheaper). This is the primary cost-saving mechanism — avoid shrinking `analysis_json`.

### Key constants to know

- `_TEXT_TAGS` / `_STRUCTURAL_TAGS` / `_SKIP_TAGS` in `epub_handler.py` — control what gets extracted
- `ANALYSIS_SECTIONS` in `prompt_builder.py` — the 6 grouped prompt batches
- `apply_french_typography()` in `translator.py` — post-processing rules (em-dash, guillemets, NNBSP)

## Environment

- Python venv: `.venv` (Homebrew Python 3.14, arm64). **Never use system `python3`** (it's x86_64).
- `ANTHROPIC_API_KEY` — set in `.env` or exported in shell. Tests mock all API calls; key not needed for tests.
- `config.yaml` — runtime config (models, token limits, output dirs). Values are validated by Pydantic models in `src/models.py`.

## Git conventions

- Branches: `feat/`, `fix/`, `release/vX.Y.Z` → `develop` (PR required) → `release/` → `main` (PR + tag)
- Commit format: `type(scope): description` (e.g. `fix(epub): ...`, `feat(cli): ...`)
- Tags: `v0.1.0`, `v0.2.0`, `v1.0.0`, `v1.1.0` on `main`
