"""Tests for analyzer module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.analyzer import (
    _merge_analysis,
    _parse_section_response,
    build_analysis_sample,
    display_analysis_summary,
    run_analysis,
)
from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.models import Config, EpubContent, SpineItem, TextNode
from src.prompt_builder import ANALYSIS_SECTIONS, PromptBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_spine_item(chap_num: int, texts: list[str]) -> SpineItem:
    nodes = [
        TextNode(xpath=f"body/p[{i}]", original_text=t)
        for i, t in enumerate(texts, 1)
    ]
    return SpineItem(
        id=f"ch{chap_num}",
        filename=f"chapter{chap_num}.xhtml",
        html_content="<p>" + "</p><p>".join(texts) + "</p>",
        text_nodes=nodes,
        is_chapter=True,
        chapter_number=chap_num,
    )


@pytest.fixture
def epub_content():
    chapters = [
        _make_spine_item(0, ["It was a dark and stormy night.", "The wind howled."]),
        _make_spine_item(1, ["Morning came at last.", "Birds sang outside."]),
        _make_spine_item(2, ["Chapter three begins here.", "More text."]),
    ]
    return EpubContent(
        book_id="test-book-abc",
        metadata={"title": "Test Novel"},
        spine_items=chapters,
    )


@pytest.fixture
def mock_client():
    client = MagicMock(spec=ClaudeClient)
    client.count_tokens = MagicMock(return_value=100)
    client.complete = AsyncMock(
        return_value=json.dumps({"identification": {"titre_original": "Test"}})
    )
    return client


@pytest.fixture
def prompt_builder(tmp_path):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True)
    translation_dir = tmp_path / "translation"
    translation_dir.mkdir()

    for section in ANALYSIS_SECTIONS:
        (analysis_dir / section["prompt_file"]).write_text(
            "Analyse ce texte.\n\n{sample_text}", encoding="utf-8"
        )

    (translation_dir / "system_prompt.md").write_text(
        "System: {analysis_json}", encoding="utf-8"
    )
    (translation_dir / "chapter_prompt.md").write_text(
        "Translate chapter {chapter_number}: {chapter_title}\n{text_nodes_json}",
        encoding="utf-8",
    )

    return PromptBuilder(tmp_path)


@pytest.fixture
def cache(tmp_path):
    return CacheManager(book_id="test-book-abc", cache_dir=tmp_path / "cache")


@pytest.fixture
def config():
    cfg = Config()
    cfg.translation.batch_delay_seconds = 0  # no delay in tests
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_section_response_plain_json():
    text = '{"identification": {"titre_original": "Test Novel"}}'
    result = _parse_section_response("identification_et_structure", text)
    assert result["identification"]["titre_original"] == "Test Novel"


def test_parse_section_response_with_fences():
    text = '```json\n{"cadre_narratif": {"point_de_vue": "1re personne"}}\n```'
    result = _parse_section_response("cadre_narratif_et_style", text)
    assert result["cadre_narratif"]["point_de_vue"] == "1re personne"


def test_parse_section_response_invalid_json():
    # Truly unrecoverable input — should return an empty dict (not raise)
    result = _parse_section_response("test", "not json at all {{{")
    assert isinstance(result, dict)


def test_build_analysis_sample_contains_text(epub_content, mock_client, config):
    sample = build_analysis_sample(epub_content.spine_items, config, mock_client)
    assert "dark and stormy night" in sample
    assert isinstance(sample, str)


def test_build_analysis_sample_includes_chapter_markers(epub_content, mock_client, config):
    sample = build_analysis_sample(epub_content.spine_items, config, mock_client)
    assert "CHAPTER" in sample


def test_merge_analysis_returns_analysis_result():
    results = {
        "identification_et_structure": {
            "identification": {"titre_original": "My Novel", "nb_chapitres": 10}
        },
        "cadre_narratif_et_style": {
            "cadre_narratif": {"point_de_vue": "1re personne"}
        },
    }
    analysis = _merge_analysis(results, "book-123")
    assert analysis.book_id == "book-123"
    assert analysis.identification["titre_original"] == "My Novel"
    assert analysis.cadre_narratif["point_de_vue"] == "1re personne"


def test_merge_analysis_extracts_personnages_and_relations():
    results = {
        "personnages_et_relations": {
            "personnages": [
                {"nom": "Alice", "genre": "féminin", "role_narratif": "protagoniste"}
            ],
            "relations": [
                {"personnages": ["Alice", "Bob"], "relation": "amicale", "registre": "tu"}
            ],
            "glossaire": [{"en": "grumpy", "fr": "grincheux", "contexte": "adjectif"}],
        }
    }
    analysis = _merge_analysis(results, "book-xyz")
    assert len(analysis.personnages) == 1
    assert analysis.personnages[0].nom == "Alice"
    assert len(analysis.relations) == 1
    assert "Alice" in analysis.relations[0].personnages
    assert len(analysis.glossaire) == 1
    assert analysis.glossaire[0].en == "grumpy"


@pytest.mark.asyncio
async def test_run_analysis_calls_all_sections(
    epub_content, mock_client, prompt_builder, cache, config
):
    analysis = await run_analysis(epub_content, mock_client, prompt_builder, cache, config)
    assert mock_client.complete.call_count == len(ANALYSIS_SECTIONS)
    assert analysis.book_id == "test-book-abc"


@pytest.mark.asyncio
async def test_run_analysis_uses_cache_on_second_call(
    epub_content, mock_client, prompt_builder, cache, config
):
    await run_analysis(epub_content, mock_client, prompt_builder, cache, config)
    first_count = mock_client.complete.call_count

    await run_analysis(epub_content, mock_client, prompt_builder, cache, config)
    assert mock_client.complete.call_count == first_count


def test_display_analysis_summary_renders():
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    console = Console(file=buf, no_color=True)
    analysis = _merge_analysis(
        {
            "identification_et_structure": {
                "identification": {
                    "titre_original": "Test",
                    "genre": "Romance",
                    "nb_chapitres": 10,
                }
            }
        },
        "test-id",
    )
    display_analysis_summary(analysis, console)
    output = buf.getvalue()
    assert len(output) > 0
