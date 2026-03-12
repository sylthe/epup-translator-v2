"""Cache and resume state management for interrupted translations."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.models import AnalysisResult, CacheState, ChapterCacheEntry, TextNode

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Persists translation state between runs.

    Layout:
    - cache_dir/
        {book_id}_state.json          — lightweight state (chapters done, flags)
        {book_id}_chapter_{n}.json    — per-chapter translated nodes
    - analysis_dir/
        {book_id}_analysis.json       — full AnalysisResult (human-readable, editable)

    All writes are atomic (write to .tmp then rename).
    """

    def __init__(
        self,
        book_id: str,
        cache_dir: str | Path,
        analysis_dir: str | Path | None = None,
    ) -> None:
        self.book_id = book_id
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Analysis lives in analysis_dir (or cache_dir as fallback)
        self.analysis_dir = Path(analysis_dir) if analysis_dir else self.cache_dir
        self.analysis_dir.mkdir(parents=True, exist_ok=True)

        self._state_path = self.cache_dir / f"{book_id}_state.json"
        self._analysis_path = self.analysis_dir / f"{book_id}_analysis.json"

        self._state = self._load_state()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> CacheState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return CacheState(**data)
            except Exception as exc:
                logger.warning("Could not load cache state: %s — starting fresh", exc)
        return CacheState(book_id=self.book_id)

    def _save_state(self) -> None:
        self._state.last_updated = datetime.now(UTC)
        _atomic_write(self._state_path, self._state.model_dump_json(indent=2))

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def is_analysis_complete(self) -> bool:
        """True if a completed analysis file exists."""
        return self._state.analysis_complete and self._analysis_path.exists()

    def save_analysis(self, analysis: AnalysisResult) -> None:
        """Persist the full AnalysisResult to analysis_dir and mark as complete."""
        _atomic_write(self._analysis_path, analysis.model_dump_json(indent=2))
        self._state.analysis_complete = True
        self._save_state()
        logger.info("Analysis saved to %s", self._analysis_path)

    def load_analysis(self) -> AnalysisResult:
        """Load and return the persisted AnalysisResult."""
        if not self._analysis_path.exists():
            raise FileNotFoundError(f"No analysis file found at {self._analysis_path}")
        data = json.loads(self._analysis_path.read_text(encoding="utf-8"))
        return AnalysisResult(**data)

    @property
    def analysis_path(self) -> Path:
        """Public path to the analysis JSON file."""
        return self._analysis_path

    # ------------------------------------------------------------------
    # Chapter results
    # ------------------------------------------------------------------

    def _chapter_path(self, chapter_num: int) -> Path:
        return self.cache_dir / f"{self.book_id}_chapter_{chapter_num:04d}.json"

    def save_chapter_result(self, chapter_num: int, text_nodes: list[TextNode]) -> None:
        """Persist the translated text nodes for a chapter."""
        entry = ChapterCacheEntry(
            chapter_number=chapter_num,
            filename="",
            text_nodes=[
                {
                    "xpath": n.xpath,
                    "original_text": n.original_text,
                    "translated_text": n.translated_text,
                    "parent_tag": n.parent_tag,
                    "attributes": n.attributes,
                }
                for n in text_nodes
            ],
        )
        _atomic_write(self._chapter_path(chapter_num), entry.model_dump_json(indent=2))

        if chapter_num not in self._state.completed_chapters:
            self._state.completed_chapters.append(chapter_num)
            self._state.completed_chapters.sort()
        self._save_state()
        logger.info("Chapter %d cached", chapter_num)

    def load_chapter_result(self, chapter_num: int) -> list[TextNode]:
        """Load and return text nodes for a previously translated chapter."""
        path = self._chapter_path(chapter_num)
        if not path.exists():
            raise FileNotFoundError(f"No cache for chapter {chapter_num} at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = ChapterCacheEntry(**data)
        return [
            TextNode(
                xpath=n["xpath"],
                original_text=n["original_text"],
                translated_text=n.get("translated_text"),
                parent_tag=n.get("parent_tag", "p"),
                attributes=n.get("attributes", {}),
            )
            for n in entry.text_nodes
        ]

    def get_last_completed_chapter(self) -> int:
        """Return the highest completed chapter number, or -1 if none."""
        if not self._state.completed_chapters:
            return -1
        return self._state.completed_chapters[-1]

    def is_chapter_complete(self, chapter_num: int) -> bool:
        return chapter_num in self._state.completed_chapters

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Delete all cache and analysis files for this book_id."""
        for path in self.cache_dir.glob(f"{self.book_id}_*"):
            path.unlink(missing_ok=True)
        if self._analysis_path.exists():
            self._analysis_path.unlink(missing_ok=True)
        self._state = CacheState(book_id=self.book_id)
        logger.info("Cache reset for book %s", self.book_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a temp file then rename (atomic on POSIX)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
