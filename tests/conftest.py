"""Shared pytest fixtures for epub-translator test suite."""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.models import AnalysisResult, Config, EpubContent, SpineItem, TextNode
from src.prompt_builder import ANALYSIS_SECTIONS, PromptBuilder


# ---------------------------------------------------------------------------
# Minimal ePub builder
# ---------------------------------------------------------------------------

CHAPTER_HTML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
  <h1>{title}</h1>
  {paragraphs}
</body>
</html>
"""


def make_epub_bytes(n_chapters: int = 3) -> bytes:
    """Build a minimal well-formed ePub with *n_chapters* chapters."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles>"
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles>"
            "</container>",
        )

        # Build manifest and spine entries
        items = "".join(
            f'<item id="ch{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>'
            for i in range(n_chapters)
        )
        items += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(n_chapters))

        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>Integration Test Novel</dc:title>"
            "<dc:creator>Test Author</dc:creator>"
            "<dc:language>en</dc:language>"
            '<dc:identifier id="bookid">integration-test-001</dc:identifier>'
            "</metadata>"
            f"<manifest>{items}</manifest>"
            f'<spine toc="ncx">{spine}</spine>'
            "</package>",
        )

        # NCX
        nav_points = "".join(
            f'<navPoint id="np{i}" playOrder="{i+1}">'
            f"<navLabel><text>Chapter {i+1}</text></navLabel>"
            f'<content src="chapter{i}.xhtml"/></navPoint>'
            for i in range(n_chapters)
        )
        zf.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head><meta name="dtb:uid" content="integration-test-001"/></head>'
            "<docTitle><text>Integration Test Novel</text></docTitle>"
            f"<navMap>{nav_points}</navMap>"
            "</ncx>",
        )

        # Chapter files
        for i in range(n_chapters):
            title = f"Chapter {i + 1}"
            paragraphs = "".join(
                f"<p>This is paragraph {j + 1} of chapter {i + 1}. It contains sample English text.</p>"
                for j in range(5)
            )
            html = CHAPTER_HTML_TEMPLATE.format(title=title, paragraphs=paragraphs)
            zf.writestr(f"OEBPS/chapter{i}.xhtml", html)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_epub(tmp_path):
    """Path to a minimal 3-chapter ePub file."""
    path = tmp_path / "test.epub"
    path.write_bytes(make_epub_bytes(3))
    return path


@pytest.fixture
def mock_claude_client():
    """
    A mocked ClaudeClient that:
    - Returns a valid analysis JSON for analysis calls
    - Returns a valid translation JSON for translation calls
    """
    client = MagicMock(spec=ClaudeClient)
    client.count_tokens = MagicMock(return_value=100)

    def _auto_response(system: str, user: str, **kwargs) -> str:
        # Analysis calls: return a generic analysis JSON
        if "JSON valide" in system or "analyse" in system.lower():
            return json.dumps({"identification": {"titre_original": "Test Novel", "nb_chapitres": 3}})
        # Translation calls: echo nodes back as translated
        try:
            # Try to extract nodes from user prompt
            import re
            match = re.search(r'\[.*\]', user, re.DOTALL)
            if match:
                nodes_raw = json.loads(match.group(0))
                translated = [
                    {"index": n["index"], "original": n["text"], "translated": f"[FR] {n['text']}"}
                    for n in nodes_raw
                ]
                return json.dumps({"translated_nodes": translated, "translation_notes": []})
        except Exception:
            pass
        return json.dumps({"translated_nodes": [], "translation_notes": []})

    client.complete = AsyncMock(side_effect=_auto_response)
    client.get_usage_summary = MagicMock(
        return_value={
            "calls": 10,
            "input_tokens": 50000,
            "output_tokens": 20000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "estimated_cost_usd": 0.45,
        }
    )
    return client


@pytest.fixture
def sample_analysis():
    return AnalysisResult(
        book_id="test-book",
        identification={
            "titre_original": "Integration Test Novel",
            "genre": "Fiction",
            "nb_chapitres": 3,
        },
        cadre_narratif={"point_de_vue": "3e personne"},
        notes_traduction=["Keep it simple."],
    )


@pytest.fixture
def test_config():
    cfg = Config()
    cfg.translation.batch_delay_seconds = 0
    cfg.translation.max_tokens_per_segment = 1000
    return cfg


@pytest.fixture
def test_prompt_builder(tmp_path):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True)
    translation_dir = tmp_path / "translation"
    translation_dir.mkdir()

    for section in ANALYSIS_SECTIONS:
        (analysis_dir / section["prompt_file"]).write_text(
            "Analyse:\n{sample_text}", encoding="utf-8"
        )

    (translation_dir / "system_prompt.md").write_text(
        "System: {analysis_json}", encoding="utf-8"
    )
    (translation_dir / "chapter_prompt.md").write_text(
        "Ch {chapter_number}: {chapter_title}\n{text_nodes_json}",
        encoding="utf-8",
    )

    return PromptBuilder(tmp_path)


@pytest.fixture
def test_cache(tmp_path):
    return CacheManager(book_id="test-book", cache_dir=tmp_path / "cache")
