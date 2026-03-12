# Changelog

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
