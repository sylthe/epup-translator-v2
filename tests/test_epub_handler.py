"""Tests for epub_handler module."""

from __future__ import annotations

import io
import zipfile

import pytest

from src.epub_handler import _extract_text_nodes, _find_by_xpath, extract_epub, reconstruct_epub
from src.models import SpineItem, TextNode


# ---------------------------------------------------------------------------
# Helpers — build a minimal valid ePub in memory
# ---------------------------------------------------------------------------

CHAPTER1_HTML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Chapter 1</title>
  <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
</head>
<body>
  <h1>Chapter One</h1>
  <p>It was a dark and stormy night.</p>
  <p>The wind howled through the trees.</p>
</body>
</html>
"""

CHAPTER2_HTML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Chapter 2</title>
  <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
</head>
<body>
  <h1>Chapter Two</h1>
  <p>Morning came at last.</p>
</body>
</html>
"""


def _build_epub_bytes() -> bytes:
    """Create a minimal well-formed ePub ZIP in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype (must be first and uncompressed)
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )

        # Container
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles>"
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles>"
            "</container>",
        )

        # OPF
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>Test Novel</dc:title>"
            "<dc:creator>Test Author</dc:creator>"
            "<dc:language>en</dc:language>"
            '<dc:identifier id="bookid">test-book-001</dc:identifier>'
            "</metadata>"
            '<manifest>'
            '<item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ch2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            "</manifest>"
            '<spine toc="ncx"><itemref idref="ch1"/><itemref idref="ch2"/></spine>'
            "</package>",
        )

        # NCX
        zf.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            "<head><meta name=\"dtb:uid\" content=\"test-book-001\"/></head>"
            "<docTitle><text>Test Novel</text></docTitle>"
            "<navMap>"
            '<navPoint id="np1" playOrder="1"><navLabel><text>Chapter One</text></navLabel>'
            '<content src="chapter1.xhtml"/></navPoint>'
            '<navPoint id="np2" playOrder="2"><navLabel><text>Chapter Two</text></navLabel>'
            '<content src="chapter2.xhtml"/></navPoint>'
            "</navMap>"
            "</ncx>",
        )

        zf.writestr("OEBPS/stylesheet.css", "p { text-indent: 1.5em; }")
        zf.writestr("OEBPS/chapter1.xhtml", CHAPTER1_HTML)
        zf.writestr("OEBPS/chapter2.xhtml", CHAPTER2_HTML)

    return buf.getvalue()


@pytest.fixture
def epub_path(tmp_path):
    p = tmp_path / "test.epub"
    p.write_bytes(_build_epub_bytes())
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_epub_returns_epub_content(epub_path):
    content = extract_epub(epub_path)
    assert content.book_id  # sha256 present
    assert content.metadata["title"] == "Test Novel"
    assert content.metadata["language"] == "en"
    assert len(content.spine_items) == 2


def test_extract_epub_text_nodes(epub_path):
    content = extract_epub(epub_path)
    # Both chapters should have text nodes
    all_nodes = [n for item in content.spine_items for n in item.text_nodes]
    texts = [n.original_text for n in all_nodes]
    assert any("dark and stormy night" in t for t in texts)
    assert any("Morning came" in t for t in texts)


def test_extract_text_nodes_preserves_structure():
    from bs4 import BeautifulSoup

    html = "<html><body><p>Hello world</p><p>Second paragraph</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    nodes = _extract_text_nodes(soup)
    assert len(nodes) == 2
    assert nodes[0].original_text == "Hello world"
    assert nodes[0].parent_tag == "p"
    assert nodes[1].original_text == "Second paragraph"


def test_find_by_xpath_basic():
    from bs4 import BeautifulSoup

    html = "<html><body><p>First</p><p>Second</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    tag = _find_by_xpath(soup, "html/body/p[2]")
    assert tag is not None
    assert tag.get_text() == "Second"


def test_reconstruct_epub_reinjects_translations(epub_path, tmp_path):
    content = extract_epub(epub_path)

    # Inject fake translations
    for item in content.spine_items:
        for node in item.text_nodes:
            node.translated_text = f"[FR] {node.original_text}"

    out = tmp_path / "translated.epub"
    result = reconstruct_epub(content, out)
    assert result.exists()
    assert result.stat().st_size > 0

    # Verify translated text is present and CSS links are preserved
    with zipfile.ZipFile(result) as z:
        html = z.read("OEBPS/chapter1.xhtml").decode("utf-8")
        assert "[FR]" in html
        assert 'rel="stylesheet"' in html
        assert "stylesheet.css" in html


def test_reconstruct_epub_language_is_fr(epub_path, tmp_path):
    import zipfile as zf_mod

    content = extract_epub(epub_path)
    out = tmp_path / "out.epub"
    reconstruct_epub(content, out)

    # The OPF should declare language as fr
    with zf_mod.ZipFile(out) as z:
        names = z.namelist()
        opf_name = next((n for n in names if n.endswith(".opf")), None)
        if opf_name:
            opf = z.read(opf_name).decode("utf-8")
            assert "fr" in opf
