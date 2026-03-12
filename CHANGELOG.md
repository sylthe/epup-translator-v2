# Changelog

## [v0.2.0] — 2026-03-11

### Added
- `prompts/analysis/` — 15 Markdown analysis prompt files
- `prompts/translation/` — system_prompt.md and chapter_prompt.md
- `src/prompt_builder.py` — PromptBuilder with ANALYSIS_SECTIONS constant
- `src/analyzer.py` — Phase 1 analysis (6 sequential API calls), JSON parsing, Rich summary table
- `--analysis-only` mode is now functionally complete (pending CLI integration in v1.0.0)
- 9 additional tests for analyzer module

## [v0.1.0] — 2026-03-11

### Added
- `src/models.py` — all dataclasses (TextNode, SpineItem, EpubContent, …) and Pydantic schemas (AnalysisResult, Config, CacheState, …)
- `src/epub_handler.py` — ePub extraction (Phase 0) and reconstruction (Phase 3) with XPath-like text node addressing
- `src/claude_client.py` — async Anthropic client with exponential retry, tiktoken counting, cost tracking
- `src/cache_manager.py` — translation state persistence and chapter-level resume
- Full project scaffold: `pyproject.toml`, `config.yaml`, module stubs, directory structure
- 15 passing tests across epub_handler and cache_manager
