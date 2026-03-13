"""Tests for translator module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.models import AnalysisResult, Config, SpineItem, TextNode
from src.prompt_builder import ANALYSIS_SECTIONS, PromptBuilder
from src.translator import (
    _parse_translation_response,
    apply_french_typography,
    apply_translations,
    get_segment_context,
    split_chapter_into_segments,
    translate_chapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nodes(texts: list[str]) -> list[TextNode]:
    return [
        TextNode(xpath=f"body/p[{i}]", original_text=t)
        for i, t in enumerate(texts, 1)
    ]


def _make_chapter(chap_num: int, texts: list[str]) -> SpineItem:
    return SpineItem(
        id=f"ch{chap_num}",
        filename=f"chapter{chap_num}.xhtml",
        html_content="",
        text_nodes=_nodes(texts),
        is_chapter=True,
        chapter_number=chap_num,
    )


@pytest.fixture
def mock_client():
    client = MagicMock(spec=ClaudeClient)
    client.count_tokens = MagicMock(return_value=50)

    def _make_translation(system, user):
        # Extract nodes from the user prompt and return fake translations
        import re
        nodes_match = re.search(r'\[.*\]', user, re.DOTALL)
        # Return a valid TranslationResult JSON for 3 dummy nodes
        return json.dumps({
            "translated_nodes": [
                {"index": 0, "original": "text0", "translated": "[FR] text0"},
                {"index": 1, "original": "text1", "translated": "[FR] text1"},
                {"index": 2, "original": "text2", "translated": "[FR] text2"},
            ],
            "translation_notes": []
        })

    client.complete = AsyncMock(side_effect=_make_translation)
    return client


@pytest.fixture
def analysis():
    return AnalysisResult(book_id="test-book", identification={"titre_original": "Test Novel"})


@pytest.fixture
def prompt_builder(tmp_path):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True)
    translation_dir = tmp_path / "translation"
    translation_dir.mkdir()

    for section in ANALYSIS_SECTIONS:
        (analysis_dir / section["prompt_file"]).write_text(
            "{sample_text}", encoding="utf-8"
        )

    (translation_dir / "system_prompt.md").write_text(
        "System: {analysis_json}", encoding="utf-8"
    )
    (translation_dir / "chapter_prompt.md").write_text(
        "Ch {chapter_number}: {chapter_title}\nContext: {segment_context}\n{text_nodes_json}",
        encoding="utf-8",
    )

    return PromptBuilder(tmp_path)


@pytest.fixture
def cache(tmp_path):
    return CacheManager(book_id="test-book", cache_dir=tmp_path / "cache")


@pytest.fixture
def config():
    cfg = Config()
    cfg.translation.batch_delay_seconds = 0
    cfg.translation.max_tokens_per_segment = 200
    cfg.translation.overlap_paragraphs = 2
    return cfg


# ---------------------------------------------------------------------------
# apply_french_typography
# ---------------------------------------------------------------------------


def test_typography_nbsp_before_punctuation():
    result = apply_french_typography("Quoi ?")
    assert "\u202f?" in result


def test_typography_nbsp_after_guillemet_open():
    result = apply_french_typography("Il dit « bonjour ».")
    assert "«\u00a0" in result
    assert "\u202f»" in result


def test_typography_ascii_quotes_become_guillemets():
    result = apply_french_typography('Elle répondit "jamais".')
    assert "«" in result and "»" in result
    assert '"' not in result


def test_typography_dialogue_dash():
    result = apply_french_typography("-- Tu viens ?")
    assert result.startswith("—")


def test_typography_idempotent():
    text = "Elle cria\u202f!"
    assert apply_french_typography(text) == text


# ---------------------------------------------------------------------------
# split_chapter_into_segments
# ---------------------------------------------------------------------------


def test_split_empty_nodes(mock_client, config):
    result = split_chapter_into_segments([], config.translation.max_tokens_per_segment, mock_client)
    assert result == []


def test_split_single_segment(mock_client):
    """All nodes fit in one segment."""
    mock_client.count_tokens = MagicMock(return_value=10)
    nodes = _nodes(["A", "B", "C"])
    segs = split_chapter_into_segments(nodes, max_tokens=100, client=mock_client)
    assert len(segs) == 1
    assert len(segs[0]) == 3


def test_split_multiple_segments(mock_client):
    """Nodes split into multiple segments."""
    mock_client.count_tokens = MagicMock(return_value=60)
    nodes = _nodes(["A", "B", "C"])
    segs = split_chapter_into_segments(nodes, max_tokens=100, client=mock_client)
    assert len(segs) > 1
    # All nodes accounted for
    total = sum(len(s) for s in segs)
    assert total == 3


# ---------------------------------------------------------------------------
# get_segment_context
# ---------------------------------------------------------------------------


def test_get_segment_context_first_segment():
    segments: list[list[TextNode]] = [_nodes(["Hello"])]
    result = get_segment_context(0, segments)
    assert result == ""


def test_get_segment_context_with_translations():
    seg0 = _nodes(["Hello", "World", "Foo"])
    for i, n in enumerate(seg0):
        n.translated_text = f"[FR] {n.original_text}"
    seg1 = _nodes(["Bar"])

    result = get_segment_context(1, [seg0, seg1], overlap=2)
    assert "World" in result or "Foo" in result
    assert result != ""


# ---------------------------------------------------------------------------
# _parse_translation_response
# ---------------------------------------------------------------------------


def test_parse_translation_response_valid():
    payload = json.dumps({
        "translated_nodes": [
            {"index": 0, "original": "Hello", "translated": "Bonjour"}
        ],
        "translation_notes": []
    })
    result = _parse_translation_response(payload)
    assert len(result.translated_nodes) == 1
    assert result.translated_nodes[0].translated == "Bonjour"


def test_parse_translation_response_with_fences():
    payload = '```json\n{"translated_nodes": [{"index": 0, "original": "Hi", "translated": "Salut"}], "translation_notes": []}\n```'
    result = _parse_translation_response(payload)
    assert result.translated_nodes[0].translated == "Salut"


def test_parse_translation_response_invalid_json():
    result = _parse_translation_response("not json at all")
    assert len(result.translated_nodes) == 0
    assert "error" in result.translation_notes[0].lower() or "Parse" in result.translation_notes[0]


# ---------------------------------------------------------------------------
# apply_translations
# ---------------------------------------------------------------------------


def test_apply_translations_sets_text():
    from src.models import TranslatedNode, TranslationResult

    nodes = _nodes(["Hello", "World"])
    result = TranslationResult(
        translated_nodes=[
            TranslatedNode(index=0, original="Hello", translated="Bonjour"),
            TranslatedNode(index=1, original="World", translated="Monde"),
        ]
    )
    apply_translations(nodes, result)
    assert nodes[0].translated_text == "Bonjour"
    assert nodes[1].translated_text == "Monde"


def test_apply_translations_ignores_out_of_range():
    from src.models import TranslatedNode, TranslationResult

    nodes = _nodes(["Hello"])
    result = TranslationResult(
        translated_nodes=[
            TranslatedNode(index=99, original="X", translated="Y")
        ]
    )
    apply_translations(nodes, result)
    assert nodes[0].translated_text is None


# ---------------------------------------------------------------------------
# translate_chapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_chapter_populates_translations(
    analysis, mock_client, prompt_builder, cache, config
):
    chapter = _make_chapter(0, ["Text A", "Text B", "Text C"])
    result_chapter = await translate_chapter(
        chapter, analysis, mock_client, prompt_builder, cache, config
    )
    # Some nodes should be translated (mock returns 3 nodes at fixed indices)
    translated = [n for n in result_chapter.text_nodes if n.translated_text is not None]
    assert len(translated) > 0


@pytest.mark.asyncio
async def test_translate_chapter_uses_cache(
    analysis, mock_client, prompt_builder, cache, config
):
    chapter = _make_chapter(1, ["Hello", "World", "Foo"])

    await translate_chapter(chapter, analysis, mock_client, prompt_builder, cache, config)
    first_call_count = mock_client.complete.call_count

    # Reset translations to test cache loading
    for node in chapter.text_nodes:
        node.translated_text = None

    await translate_chapter(chapter, analysis, mock_client, prompt_builder, cache, config)
    assert mock_client.complete.call_count == first_call_count
    # Cache should have restored translations
    assert cache.is_chapter_complete(1)
