"""ePub extraction and reconstruction (Phase 0 and Phase 3)."""

from __future__ import annotations

import hashlib
import re
import warnings
from pathlib import Path
from typing import Any

import ebooklib
from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning
from ebooklib import epub

# Suppress BeautifulSoup's XMLParsedAsHTMLWarning — ePub XHTML is intentionally
# parsed with the HTML parser for robustness.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from src.models import EpubContent, Font, Image, SpineItem, StyleSheet, TextNode, TocEntry


# Tags whose direct text content should be extracted as text nodes.
_TEXT_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "caption", "blockquote",
    "div", "span", "em", "strong", "i", "b", "a",
}

# Tags that are purely structural — we recurse into them but don't extract at this level.
_STRUCTURAL_TAGS = {"body", "section", "article", "main", "header", "footer", "nav", "aside", "ul", "ol", "table", "thead", "tbody", "tr"}

# Tags to skip entirely.
_SKIP_TAGS = {"script", "style", "head", "meta", "link", "title"}


def _sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def _slug(text: str) -> str:
    """Convert a title to a safe filename slug (lowercase, hyphens, ASCII)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)   # remove punctuation
    text = re.sub(r"[\s_]+", "-", text)    # spaces/underscores → hyphens
    text = re.sub(r"-+", "-", text)        # collapse multiple hyphens
    return text[:50].strip("-") or "book"  # cap at 50 chars


def _make_book_id(title: str | None, path: Path) -> str:
    """Return a human-readable, deterministic book ID: slug-XXXXXXXX."""
    slug = _slug(title or path.stem)
    return f"{slug}-{_sha256_short(path)}"


def _build_xpath(tag: Tag) -> str:
    """Build a simple XPath-like address for a BS4 tag (e.g. 'body/div[2]/p[1]')."""
    parts: list[str] = []
    node: Tag | None = tag
    while node and node.name and node.name != "[document]":
        parent = node.parent
        if parent is None:
            parts.append(node.name)
            break
        siblings = [s for s in parent.children if isinstance(s, Tag) and s.name == node.name]
        if len(siblings) > 1:
            idx = siblings.index(node) + 1
            parts.append(f"{node.name}[{idx}]")
        else:
            parts.append(node.name)
        node = parent  # type: ignore[assignment]
    parts.reverse()
    return "/".join(parts)


def _extract_text_nodes(soup: BeautifulSoup) -> list[TextNode]:
    """
    Walk the HTML tree and extract translatable text nodes.

    Strategy:
    - Only extract leaf-ish tags that directly contain non-whitespace text.
    - Skip nodes whose text is already captured by a child node.
    - Build an XPath-like address for each node so text can be re-injected later.
    """
    nodes: list[TextNode] = []
    visited: set[int] = set()

    def _walk(element: Any, depth: int = 0) -> None:
        if not isinstance(element, Tag):
            return
        if element.name in _SKIP_TAGS:
            return

        # Collect direct text content (ignoring whitespace-only strings)
        direct_texts = [
            str(child) for child in element.children
            if isinstance(child, NavigableString) and str(child).strip()
        ]
        child_tags = [child for child in element.children if isinstance(child, Tag)]

        tag_name = element.name or ""

        if tag_name in _TEXT_TAGS and direct_texts and id(element) not in visited:
            # If this element has meaningful direct text, capture it.
            full_text = element.get_text(separator=" ", strip=True)
            if full_text:
                visited.add(id(element))
                attrs: dict[str, Any] = {}
                for k, v in element.attrs.items():
                    attrs[k] = v if not isinstance(v, list) else " ".join(v)
                nodes.append(
                    TextNode(
                        xpath=_build_xpath(element),
                        original_text=full_text,
                        parent_tag=tag_name,
                        attributes=attrs,
                    )
                )
                # Mark ancestors so we don't double-extract
                parent = element.parent
                while parent and parent.name and parent.name != "[document]":
                    visited.add(id(parent))
                    parent = parent.parent
                return  # don't recurse — text captured at this level

        # Recurse into children
        for child in child_tags:
            _walk(child, depth + 1)

    _walk(soup)
    return nodes


def _is_chapter(item: epub.EpubItem, spine_index: int) -> bool:
    """Heuristic: is this spine item a narrative chapter?"""
    name = (item.get_name() or "").lower()
    # Skip known non-narrative items
    for skip in ("cover", "toc", "nav", "ncx", "copyright", "dedication",
                 "title", "colophon", "about", "appendix", "index", "halftitle"):
        if skip in name:
            return False
    return True


def extract_epub(path: str | Path) -> EpubContent:
    """
    Open an ePub file and return a fully-populated EpubContent.

    Preserves the original HTML trees, CSS, images, and fonts.
    Extracts text nodes for translation without modifying the HTML.
    """
    path = Path(path)
    book: epub.EpubBook = epub.read_epub(str(path))

    # ---- Metadata ----
    metadata: dict[str, Any] = {
        "title": _first(book.get_metadata("DC", "title")),
        "author": _first(book.get_metadata("DC", "creator")),
        "language": _first(book.get_metadata("DC", "language")),
        "publisher": _first(book.get_metadata("DC", "publisher")),
        "identifier": _first(book.get_metadata("DC", "identifier")),
        "description": _first(book.get_metadata("DC", "description")),
        "date": _first(book.get_metadata("DC", "date")),
        "rights": _first(book.get_metadata("DC", "rights")),
    }

    book_id = _make_book_id(metadata.get("title"), path)

    # ---- Spine items ----
    spine_items: list[SpineItem] = []
    chapter_counter = 0

    for spine_id, _linear in book.spine:
        item = book.get_item_with_id(spine_id)
        if item is None:
            continue
        if item.get_type() not in (
            ebooklib.ITEM_DOCUMENT,
            ebooklib.ITEM_NAVIGATION,
        ):
            continue

        raw_content = item.get_content()
        if raw_content is None:
            continue

        html_str = raw_content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_str, "lxml")
        text_nodes = _extract_text_nodes(soup)

        is_chap = _is_chapter(item, len(spine_items))
        chap_num: int | None = None
        if is_chap:
            chap_num = chapter_counter
            chapter_counter += 1

        spine_items.append(
            SpineItem(
                id=spine_id,
                filename=item.get_name() or f"item_{spine_id}",
                html_content=html_str,
                text_nodes=text_nodes,
                is_chapter=is_chap,
                chapter_number=chap_num,
            )
        )

    # ---- CSS ----
    styles = [
        StyleSheet(filename=item.get_name() or f"style_{i}.css", content=item.get_content() or b"")
        for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_STYLE))
    ]

    # ---- Images ----
    images = [
        Image(
            filename=item.get_name() or f"img_{i}",
            media_type=item.media_type or "image/jpeg",
            content=item.get_content() or b"",
        )
        for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_IMAGE))
    ]

    # ---- Fonts ----
    fonts = [
        Font(
            filename=item.get_name() or f"font_{i}",
            media_type=item.media_type or "application/font-woff",
            content=item.get_content() or b"",
        )
        for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_FONT))
    ]

    # ---- TOC ----
    toc = _build_toc(book.toc)

    return EpubContent(
        book_id=book_id,
        metadata=metadata,
        spine_items=spine_items,
        styles=styles,
        images=images,
        fonts=fonts,
        toc=toc,
    )


def _first(meta: list[Any]) -> str | None:
    """Return the first non-empty metadata value."""
    for item in meta:
        if isinstance(item, tuple) and item[0]:
            return str(item[0])
        if isinstance(item, str) and item:
            return item
    return None


def _build_toc(toc_items: Any, level: int = 0) -> list[TocEntry]:
    entries: list[TocEntry] = []
    for item in toc_items:
        if isinstance(item, tuple):
            section, children = item
            entry = TocEntry(
                title=section.title if hasattr(section, "title") else str(section),
                href=section.href if hasattr(section, "href") else "",
                level=level,
                children=_build_toc(children, level + 1),
            )
            entries.append(entry)
        elif hasattr(item, "title"):
            entries.append(
                TocEntry(
                    title=item.title,
                    href=item.href if hasattr(item, "href") else "",
                    level=level,
                )
            )
    return entries


def reconstruct_epub(content: EpubContent, output_path: str | Path) -> Path:
    """
    Rebuild the ePub from the (partially) translated EpubContent.

    For each SpineItem:
    - Parse the stored HTML with BeautifulSoup.
    - For each TextNode whose translated_text is set, locate the node by xpath
      and replace its text content.
    - Serialise the modified soup back to bytes.

    Non-text resources (CSS, images, fonts) are copied verbatim.
    Metadata is updated: dc:language → fr, dc:contributor added.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    new_book = epub.EpubBook()

    # Metadata
    meta = content.metadata
    if meta.get("title"):
        new_book.set_title(meta["title"])
    if meta.get("author"):
        new_book.add_author(meta["author"])
    new_book.set_language("fr")
    if meta.get("identifier"):
        new_book.set_identifier(meta["identifier"])
    new_book.add_metadata("DC", "contributor", "Traduit par IA (Claude)")

    # Spine items
    spine_ids: list[str] = []
    for item in content.spine_items:
        translated_html = _apply_translations(item)
        epub_item = epub.EpubHtml(
            uid=item.id,
            file_name=item.filename,
            media_type="application/xhtml+xml",
            content=translated_html.encode("utf-8"),
        )
        new_book.add_item(epub_item)
        spine_ids.append(item.id)

    # CSS — append French typography rules to first stylesheet (or create one)
    styles = list(content.styles)
    if styles:
        first = styles[0]
        patched = StyleSheet(
            filename=first.filename,
            content=first.content + _FRENCH_TYPOGRAPHY_CSS,
        )
        styles = [patched] + styles[1:]
    else:
        styles = [StyleSheet(filename="french-typography.css", content=_FRENCH_TYPOGRAPHY_CSS)]
        # Link the new stylesheet in every spine item HTML
        # (handled below via _apply_translations which injects a <link> when no styles exist)

    for style in styles:
        css_item = epub.EpubItem(
            uid=f"css_{style.filename}",
            file_name=style.filename,
            media_type="text/css",
            content=style.content,
        )
        new_book.add_item(css_item)

    # Images
    for img in content.images:
        img_item = epub.EpubItem(
            uid=f"img_{img.filename}",
            file_name=img.filename,
            media_type=img.media_type,
            content=img.content,
        )
        new_book.add_item(img_item)

    # Fonts
    for font in content.fonts:
        font_item = epub.EpubItem(
            uid=f"font_{font.filename}",
            file_name=font.filename,
            media_type=font.media_type,
            content=font.content,
        )
        new_book.add_item(font_item)

    # TOC and spine
    new_book.toc = _toc_to_epub(content.toc)
    new_book.spine = spine_ids
    new_book.add_item(epub.EpubNcx())
    new_book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), new_book)
    return output_path


# French typography CSS appended to the first existing stylesheet.
# Rules follow the classic French norm:
#   - every paragraph gets a 1em indent
#   - EXCEPT the first paragraph of a section and the first after a heading or hr
_FRENCH_TYPOGRAPHY_CSS: bytes = b"""
/* === Typographie francaise (epub-translator) === */
p {
  text-indent: 1em;
  margin-top: 0;
  margin-bottom: 0;
}
/* No indent: first paragraph of a block, after headings, after scene-break */
p:first-child,
h1 + p, h2 + p, h3 + p, h4 + p, h5 + p, h6 + p,
hr + p,
p.noindent {
  text-indent: 0;
}
h1, h2, h3, h4, h5, h6 {
  text-indent: 0;
}
"""


# Block-level tags that can be split into sibling elements for dialogue breaks.
_BLOCK_TAGS = {"p", "div", "li", "td", "th", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


def _apply_translations(item: SpineItem) -> str:
    """
    Reinjection: replace text content of HTML nodes with their translations.

    Uses xpath addresses to locate nodes; falls back gracefully if a node
    can no longer be found (e.g. the HTML was altered externally).

    If a translated text contains newlines (paragraph-break markers inserted
    by apply_french_typography for em-dash dialogue splits) AND the tag is a
    block-level element, the original tag is replaced by one sibling tag per
    line.  For inline elements (span, em, strong…), newlines are flattened to
    a space to avoid rendering two inline spans side-by-side.
    """
    soup = BeautifulSoup(item.html_content, "lxml")

    for node in item.text_nodes:
        if node.translated_text is None:
            continue
        tag = _find_by_xpath(soup, node.xpath)
        if tag is None:
            continue

        translated = node.translated_text
        parts = translated.split("\n")

        if len(parts) == 1 or tag.name not in _BLOCK_TAGS:
            # Inline element or no split needed: flatten newlines to space
            text = " ".join(p.strip() for p in parts if p.strip())
            for child in list(tag.children):
                child.extract()
            tag.append(NavigableString(text))
        else:
            # Block element: replace with one sibling <p> per line
            parent = tag.parent
            if parent is None:
                for child in list(tag.children):
                    child.extract()
                tag.append(NavigableString(translated.replace("\n", " ")))
                continue
            insert_pos = list(parent.children).index(tag)
            tag_name = tag.name
            tag.decompose()
            inserted = 0
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                new_tag = soup.new_tag(tag_name)
                new_tag.append(NavigableString(part))
                parent.insert(insert_pos + inserted, new_tag)
                inserted += 1

    return str(soup)


def _find_by_xpath(soup: BeautifulSoup, xpath: str) -> Tag | None:
    """
    Locate a BS4 Tag by its xpath-like address (e.g. 'html/body/div[2]/p[1]').
    Returns None if not found.
    """
    parts = xpath.split("/")
    current: Any = soup

    for part in parts:
        m = re.match(r"^(\w+)(?:\[(\d+)\])?$", part)
        if not m:
            return None
        tag_name, idx_str = m.group(1), m.group(2)
        idx = int(idx_str) if idx_str else 1

        matching = [child for child in current.children if isinstance(child, Tag) and child.name == tag_name]
        if len(matching) < idx:
            return None
        current = matching[idx - 1]

    return current if isinstance(current, Tag) else None


def _toc_to_epub(entries: list[TocEntry]) -> list[Any]:
    result = []
    for entry in entries:
        link = epub.Link(entry.href, entry.title, entry.href)
        if entry.children:
            result.append((epub.Section(entry.title), _toc_to_epub(entry.children)))
        else:
            result.append(link)
    return result
