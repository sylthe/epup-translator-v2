"""Tests for cache_manager module."""

from __future__ import annotations

import pytest

from src.cache_manager import CacheManager
from src.models import AnalysisResult, TextNode


@pytest.fixture
def cache(tmp_path):
    return CacheManager(book_id="test-book-abc123", cache_dir=tmp_path)


def _sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        book_id="test-book-abc123",
        identification={"titre_original": "Test Novel"},
        notes_traduction=["Keep it simple"],
    )


def _sample_nodes() -> list[TextNode]:
    return [
        TextNode(xpath="body/p[1]", original_text="Hello", translated_text="Bonjour"),
        TextNode(xpath="body/p[2]", original_text="World", translated_text="Monde"),
    ]


# ---------------------------------------------------------------------------


def test_initial_state_no_analysis(cache):
    assert not cache.is_analysis_complete()


def test_save_and_load_analysis(cache):
    analysis = _sample_analysis()
    cache.save_analysis(analysis)

    assert cache.is_analysis_complete()
    loaded = cache.load_analysis()
    assert loaded.book_id == "test-book-abc123"
    assert loaded.identification["titre_original"] == "Test Novel"
    assert loaded.notes_traduction == ["Keep it simple"]


def test_initial_last_chapter_is_minus_one(cache):
    assert cache.get_last_completed_chapter() == -1


def test_save_and_get_chapter(cache):
    nodes = _sample_nodes()
    cache.save_chapter_result(0, nodes)

    assert cache.is_chapter_complete(0)
    assert cache.get_last_completed_chapter() == 0


def test_multiple_chapters_ordering(cache):
    cache.save_chapter_result(2, _sample_nodes())
    cache.save_chapter_result(0, _sample_nodes())
    cache.save_chapter_result(1, _sample_nodes())

    assert cache.get_last_completed_chapter() == 2
    assert cache.is_chapter_complete(1)


def test_load_chapter_result(cache):
    nodes = _sample_nodes()
    cache.save_chapter_result(3, nodes)

    loaded = cache.load_chapter_result(3)
    assert len(loaded) == 2
    assert loaded[0].original_text == "Hello"
    assert loaded[0].translated_text == "Bonjour"


def test_load_chapter_missing_raises(cache):
    with pytest.raises(FileNotFoundError):
        cache.load_chapter_result(99)


def test_state_persists_across_instances(tmp_path):
    c1 = CacheManager(book_id="persist-test", cache_dir=tmp_path)
    c1.save_chapter_result(0, _sample_nodes())

    c2 = CacheManager(book_id="persist-test", cache_dir=tmp_path)
    assert c2.is_chapter_complete(0)
    assert c2.get_last_completed_chapter() == 0


def test_reset_clears_state(cache):
    cache.save_analysis(_sample_analysis())
    cache.save_chapter_result(0, _sample_nodes())
    cache.reset()

    assert not cache.is_analysis_complete()
    assert cache.get_last_completed_chapter() == -1
