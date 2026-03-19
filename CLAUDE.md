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

**Phase 1 (Analysis)** — `src/analyzer.py`: 6 sequential API calls (Haiku) against a sample of the book, each answering a different prompt file from `prompts/analysis/`. Produces a single `AnalysisResult` (Pydantic) saved to `output/analysis/{book_id}_analysis.json`. Returns `(sample_text, coverage_pct)` — coverage is displayed in colour (green ≥80%, yellow ≥40%, red <40%).

**Phase 2 (Translation)** — `src/translator.py`: each chapter's `TextNode` list is split into segments (≤12 000 source tokens). Each segment call injects the full analysis JSON as a cached system prompt, plus 3 overlap paragraphs from the previous segment. Uses `claude-sonnet`. Responses are validated with `json-repair`; untranslated nodes trigger a retry. `apply_french_typography()` post-processes plain-text nodes. After each chapter, `enrich_analysis_from_chapter()` calls Haiku to detect new characters and terms and enriches the in-memory `AnalysisResult`.

### Text node extraction and reinjection (`src/epub_handler.py`)

`_extract_text_nodes()` walks the BS4 tree and builds `TextNode` objects, each with an XPath-like address (`body/div[2]/p[1]`). Key rules:
- A tag is captured whole if it has non-whitespace `NavigableString` children.
- Adjacent `<span>` children with **no NavigableString between them** (word-split Calibre artifact) also force capture at parent level via `_has_adjacent_span_children()`.
- **Dropcap paragraphs** (`<p dropcap_chars="N">` or child `<span dropcap="true">`) are always captured at `<p>` level regardless of children.
- **HTML node mode**: if the captured element contains inline formatting tags (`em`, `strong`, `a`, `sup`, `sub`, `abbr`, `cite`, `code`, `s`, `u`), `inner_html = element.decode_contents()` is stored. The LLM receives `{"html": "..."}` instead of `{"text": "..."}` and must return translated HTML.

`_apply_translations()` reinserts text by xpath. Priority order for each node:
1. **HTML node** (`inner_html is not None`): parse `translated_text` as HTML, replace element's children verbatim.
2. **Dropcap** (block element with `<span dropcap="true">` child): split translated text at `dropcap_chars` boundary, reconstruct the two-span structure (dropcap span + body span with dominant CSS class).
3. **Single-line block**: wrap in dominant span class to preserve CSS font overrides.
4. **Multi-line block** (dialogue split via `\n` in translated text): create sibling `<p>` elements, each wrapped with the dominant span class.

Reconstruction (`reconstruct_epub`) copies the source zip byte-for-byte, replacing only translated HTML files. After BS4 processing:
- The original `<head>` is restored verbatim (ebooklib strips `<link>` tags).
- The original `<body>` opening tag is restored (lxml/ebooklib strip `class` attributes like `class="class3"` which carry inherited `text-indent`).

### Data flow for resume

`CacheManager` (keyed by `book_id = title-slug + 8-char SHA256`) writes atomically:
- `output/cache/{book_id}/state.json` — completed chapter list
- `output/cache/{book_id}/chapter_{NNNN}.json` — serialised `TextNode` list with `translated_text` and `inner_html`
- `output/analysis/{book_id}_analysis.json` — editable `AnalysisResult` (updated after each chapter by glossary enrichment)

Cached `TextNode` lists are **always** loaded from cache before reconstruction, even without `--resume`. The `--retranslate/-r` flag calls `cache.invalidate_chapter()` to force retranslation of one chapter while keeping all others.

### Prompt caching (cost)

The system prompt (analysis JSON, ~25 000 tokens) is marked `cache_control: ephemeral` on the first segment call. Subsequent segments within the same run pay cache-read rates (~10× cheaper). This is the primary cost-saving mechanism — avoid shrinking `analysis_json`.

### Key constants to know

- `_TEXT_TAGS` / `_STRUCTURAL_TAGS` / `_SKIP_TAGS` in `epub_handler.py` — control what gets extracted
- `_INLINE_FORMAT_TAGS` in `epub_handler.py` — tags that trigger HTML node mode
- `ANALYSIS_SECTIONS` in `prompt_builder.py` — the 6 grouped prompt batches
- `apply_french_typography()` in `translator.py` — post-processing rules (em-dash, guillemets, NNBSP); skipped for HTML nodes

## Environment

- Python venv: `.venv` (Homebrew Python 3.14, arm64). **Never use system `python3`** (it's x86_64).
- `ANTHROPIC_API_KEY` — set in `.env` or exported in shell. Tests mock all API calls; key not needed for tests.
- `config.yaml` — runtime config (models, token limits, output dirs). Values are validated by Pydantic models in `src/models.py`.

## Git conventions

- Branches: `feat/`, `fix/`, `release/vX.Y.Z` → `develop` (PR required) → `release/` → `main` (PR + tag)
- Commit format: `type(scope): description` (e.g. `fix(epub): ...`, `feat(cli): ...`)
- Tags: `v0.1.0`, `v0.2.0`, `v1.0.0`, `v1.1.0`, `v1.2.0` on `main`
