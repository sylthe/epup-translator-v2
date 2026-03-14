"""
Integration test: full pipeline on a minimal 3-chapter ePub with mocked API.

Tests the complete flow:
  extract_epub → run_analysis → translate_chapter × 3 → reconstruct_epub
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analyzer import run_analysis
from src.epub_handler import extract_epub, reconstruct_epub
from src.models import Config
from src.translator import translate_chapter


@pytest.mark.asyncio
async def test_full_pipeline(
    minimal_epub,
    tmp_path,
    mock_claude_client,
    sample_analysis,
    test_config,
    test_prompt_builder,
    test_cache,
):
    """
    End-to-end pipeline: extract → analyse → translate all chapters → reconstruct.
    Verifies that the output ePub is valid and contains French content.
    """
    # ---- Phase 0: Extract ----
    content = extract_epub(minimal_epub)
    assert content.book_id
    chapters = [item for item in content.spine_items if item.is_chapter]
    assert len(chapters) == 3

    # ---- Phase 1: Analysis (cached after first run) ----
    analysis = await run_analysis(
        content, mock_claude_client, test_prompt_builder, test_cache, test_config
    )
    assert analysis.book_id == content.book_id
    assert test_cache.is_analysis_complete()

    # ---- Phase 2: Translate each chapter ----
    for chapter in chapters:
        await translate_chapter(
            chapter=chapter,
            analysis=analysis,
            client=mock_claude_client,
            prompt_builder=test_prompt_builder,
            cache=test_cache,
            config=test_config,
        )
        assert test_cache.is_chapter_complete(chapter.chapter_number or 0)

    # ---- Phase 3: Reconstruct ----
    output = tmp_path / "translated.epub"
    result = reconstruct_epub(content, output)

    assert result.exists()
    assert result.stat().st_size > 0

    # Verify it's a valid ZIP (ePub)
    assert zipfile.is_zipfile(result)

    # The OPF should declare French
    with zipfile.ZipFile(result) as z:
        opf_files = [n for n in z.namelist() if n.endswith(".opf")]
        if opf_files:
            opf_content = z.read(opf_files[0]).decode("utf-8")
            assert ">fr<" in opf_content or "fr</dc:language>" in opf_content


@pytest.mark.asyncio
async def test_resume_from_cache(
    minimal_epub,
    tmp_path,
    mock_claude_client,
    sample_analysis,
    test_config,
    test_prompt_builder,
    test_cache,
):
    """
    After translating 1 chapter, a new CacheManager should see it as complete.
    """
    from src.cache_manager import CacheManager

    content = extract_epub(minimal_epub)
    chapters = [item for item in content.spine_items if item.is_chapter]

    # Translate only the first chapter
    await translate_chapter(
        chapter=chapters[0],
        analysis=sample_analysis,
        client=mock_claude_client,
        prompt_builder=test_prompt_builder,
        cache=test_cache,
        config=test_config,
    )

    # New instance — simulates process restart (same book_id as the cache)
    new_cache = CacheManager(test_cache.book_id, test_cache.cache_dir.parent)
    assert new_cache.is_chapter_complete(0)
    last = new_cache.get_last_completed_chapter()
    assert last == 0  # only first chapter done


@pytest.mark.asyncio
async def test_analysis_not_repeated_when_cached(
    minimal_epub,
    mock_claude_client,
    test_config,
    test_prompt_builder,
    test_cache,
):
    """Second call to run_analysis should hit cache, not make new API calls."""
    content = extract_epub(minimal_epub)

    await run_analysis(content, mock_claude_client, test_prompt_builder, test_cache, test_config)
    first_call_count = mock_claude_client.complete.call_count

    await run_analysis(content, mock_claude_client, test_prompt_builder, test_cache, test_config)
    assert mock_claude_client.complete.call_count == first_call_count


def test_cli_help(tmp_path):
    """Smoke test: CLI help runs without error."""
    from click.testing import CliRunner

    from src.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "translate" in result.output


def test_cli_translate_help():
    from click.testing import CliRunner

    from src.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["translate", "--help"])
    assert result.exit_code == 0
    assert "--analysis-only" in result.output
    assert "--resume" in result.output
