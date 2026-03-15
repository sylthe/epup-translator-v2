"""ePub extraction and reconstruction (Phase 0 and Phase 3)."""

from __future__ import annotations

import hashlib
import io
import re
import warnings
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import logging

import ebooklib
from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning
from ebooklib import epub
from PIL import Image as PILImage

# Suppress BeautifulSoup's XMLParsedAsHTMLWarning — ePub XHTML is intentionally
# parsed with the HTML parser for robustness.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from src.models import EpubContent, Font, Image, SpineItem, StyleSheet, TextNode, TocEntry

logger = logging.getLogger(__name__)

_HEADING_TAGS_SET = {"h1", "h2", "h3", "h4", "h5", "h6"}

_NONCHAPTER_LABELS: dict[str, str] = {
    "cover": "Couverture",
    "toc": "Table des matières",
    "nav": "Navigation",
    "copyright": "Copyright",
    "dedication": "Dédicace",
    "title": "Page de titre",
    "colophon": "Colophon",
    "about": "À propos",
    "appendix": "Annexe",
    "index": "Index",
    "halftitle": "Faux-titre",
}


def extract_item_title(item: SpineItem, *, translated: bool = False) -> str | None:
    """Return the text of the first heading node in a spine item.

    Checks both parent_tag and xpath (handles nested cases like <h2><em>…</em></h2>
    where parent_tag would be "em" rather than "h2").
    If translated=True, returns the translated text (None if not yet translated).
    """
    for node in item.text_nodes:
        in_heading = node.parent_tag in _HEADING_TAGS_SET or any(
            p in _HEADING_TAGS_SET for p in re.findall(r"[a-z0-9]+", node.xpath)
        )
        if in_heading:
            return node.translated_text if translated else node.original_text
    return None


def classify_nonchapter_item(filename: str) -> str:
    """Return a human-readable French label for a non-chapter spine item."""
    name = filename.lower()
    for key, label in _NONCHAPTER_LABELS.items():
        if key in name:
            return label
    return Path(filename).stem


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

    def _walk(element: Any) -> None:
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
            _walk(child)

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
        source_path=path,
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
    Rebuild the ePub by copying the original zip byte-for-byte, replacing only
    the translated HTML spine items and patching the OPF metadata.

    All other resources (CSS, fonts, images, NCX, nav) are preserved verbatim,
    so the original typography and layout are identical to the source.
    """
    if content.source_path is None:
        raise ValueError("source_path requis pour la reconstruction")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spine_map = {item.filename: item for item in content.spine_items}
    tmp = output_path.with_suffix(".tmp.epub")
    with zipfile.ZipFile(content.source_path, "r") as zin, \
         zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in zin.namelist():
            zout.writestr(
                zipfile.ZipInfo("mimetype"),
                zin.read("mimetype"),
                compress_type=zipfile.ZIP_STORED,
            )
        for info in zin.infolist():
            if info.filename == "mimetype":
                continue
            data = zin.read(info.filename)
            spine_item = spine_map.get(info.filename) or next(
                (v for k, v in spine_map.items() if info.filename.endswith("/" + k)),
                None,
            )
            if spine_item is not None:
                original_html = data.decode("utf-8", errors="replace")
                data = _apply_translations(spine_item, original_html).encode("utf-8")
            elif info.filename.endswith(".opf"):
                data = _patch_opf_metadata(data)
            elif info.filename.endswith(".ncx"):
                data = _patch_ncx(data, spine_map)
            zout.writestr(info, data)
    tmp.replace(output_path)
    return output_path


def _patch_opf_metadata(opf_bytes: bytes) -> bytes:
    """Set dc:language to 'fr' and add a translator credit in the OPF."""
    text = opf_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"<dc:language>[^<]*</dc:language>", "<dc:language>fr</dc:language>", text)
    if "Traduit par IA" not in text:
        text = re.sub(
            r"(</metadata>)",
            "  <dc:contributor>Traduit par IA (Claude)</dc:contributor>\n  \\1",
            text,
        )
    return text.encode("utf-8")


def _patch_ncx(ncx_bytes: bytes, spine_map: dict[str, "SpineItem"]) -> bytes:
    """Replace each navLabel text with the translated chapter heading when available."""
    text = ncx_bytes.decode("utf-8", errors="replace")

    def _replace(m: re.Match) -> str:
        nav_xml = m.group(0)
        src_m = re.search(r'<content[^>]+src="([^"#]+)', nav_xml)
        label_m = re.search(r'(<navLabel[^>]*>\s*<text>)([^<]*)(</text>)', nav_xml)
        if not src_m or not label_m:
            return nav_xml
        filename = src_m.group(1)
        spine_item = spine_map.get(filename) or next(
            (v for k, v in spine_map.items() if filename.endswith("/" + k) or k.endswith("/" + filename)),
            None,
        )
        if spine_item is None:
            return nav_xml
        _HEADING_TAGS = {"h1", "h2", "h3"}
        for node in spine_item.text_nodes:
            if not node.translated_text or node.translated_text.strip().isdigit():
                continue
            in_heading = node.parent_tag in _HEADING_TAGS or \
                any(p in _HEADING_TAGS for p in re.findall(r"[a-z0-9]+", node.xpath))
            if in_heading:
                orig_label = label_m.group(2)
                prefix_m = re.match(r"^(\d+\s*[-–]\s*)", orig_label)
                prefix = prefix_m.group(1) if prefix_m else ""
                return nav_xml[: label_m.start(2)] + prefix + node.translated_text + nav_xml[label_m.end(2) :]
        return nav_xml

    text = re.sub(r"<navPoint\b[^>]*>.*?</navPoint>", _replace, text, flags=re.DOTALL)
    return text.encode("utf-8")


# Block-level tags that can be split into sibling elements for dialogue breaks.
_BLOCK_TAGS = {"p", "div", "li", "td", "th", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}

# Pre-compiled regex for xpath part parsing: "tagname" or "tagname[N]"
_XPATH_PART_RE = re.compile(r"^(\w+)(?:\[(\d+)\])?$")


def _apply_translations(item: SpineItem, original_html: str | None = None) -> str:
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

    # Process in reverse order so that splitting a block element (em-dash dialogue)
    # into multiple siblings does not shift the xpath indices of preceding nodes.
    for node in reversed(item.text_nodes):
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
            insert_pos = next(i for i, c in enumerate(parent.children) if c is tag)
            tag_name = tag.name
            tag_attrs = dict(tag.attrs)  # save before decompose
            tag.decompose()
            inserted = 0
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                new_tag = soup.new_tag(tag_name, attrs=tag_attrs)
                new_tag.append(NavigableString(part))
                parent.insert(insert_pos + inserted, new_tag)
                inserted += 1

    result = str(soup)

    # BeautifulSoup/lxml mangles the <head> (strips <link> and <meta> tags),
    # breaking CSS references. Restore the original <head> verbatim since all
    # our modifications are in <body>.
    # Use original_html (direct from zip) as it preserves <link> tags that
    # ebooklib strips when building item.html_content.
    orig_head = re.search(r"<head[^>]*>.*?</head>", original_html or item.html_content, re.DOTALL | re.IGNORECASE)
    new_head = re.search(r"<head[^>]*>.*?</head>", result, re.DOTALL | re.IGNORECASE)
    if orig_head and new_head:
        result = result[: new_head.start()] + orig_head.group() + result[new_head.end() :]

    return result


def _find_by_xpath(soup: BeautifulSoup, xpath: str) -> Tag | None:
    """
    Locate a BS4 Tag by its xpath-like address (e.g. 'html/body/div[2]/p[1]').
    Returns None if not found.
    """
    parts = xpath.split("/")
    current: Any = soup

    for part in parts:
        m = _XPATH_PART_RE.match(part)
        if not m:
            return None
        tag_name, idx_str = m.group(1), m.group(2)
        idx = int(idx_str) if idx_str else 1

        count = 0
        found = None
        for child in current.children:
            if isinstance(child, Tag) and child.name == tag_name:
                count += 1
                if count == idx:
                    found = child
                    break
        if found is None:
            return None
        current = found

    return current if isinstance(current, Tag) else None


# ---------------------------------------------------------------------------
# Cover badge
# ---------------------------------------------------------------------------

_OPF_NS = "http://www.idpf.org/2007/opf"


def _find_cover_in_open_zip(z: zipfile.ZipFile) -> str | None:
    """Return the zip entry name of the cover image, or None if not found."""
    try:
        container = ET.fromstring(z.read("META-INF/container.xml"))
    except Exception:
        return None
    rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    if rootfile is None:
        rootfile = container.find(".//rootfile")
    if rootfile is None:
        return None
    opf_path = rootfile.get("full-path", "")
    if not opf_path:
        return None
    opf_dir = str(Path(opf_path).parent).rstrip(".")

    try:
        opf = ET.fromstring(z.read(opf_path))
    except Exception:
        return None

    manifest_items: dict[str, str] = {}
    epub3_cover: str | None = None
    for item in opf.iter(f"{{{_OPF_NS}}}item"):
        item_id = item.get("id", "")
        href = item.get("href", "")
        manifest_items[item_id] = href
        if epub3_cover is None and "cover-image" in item.get("properties", ""):
            epub3_cover = (f"{opf_dir}/{href}" if opf_dir else href).lstrip("/")

    if epub3_cover:
        return epub3_cover

    # EPUB2: <meta name="cover" content="id"/>
    cover_id: str | None = None
    for meta in list(opf.iter(f"{{{_OPF_NS}}}meta")) + list(opf.iter("meta")):
        if meta.get("name") == "cover":
            cover_id = meta.get("content")
            break

    if cover_id and cover_id in manifest_items:
        href = manifest_items[cover_id]
        return (f"{opf_dir}/{href}" if opf_dir else href).lstrip("/")

    return None


def apply_cover_badge(source_dir: Path, output_epub_path: Path, badge_path: Path) -> bool:
    """Overlay badge_path onto cover.jpg from source_dir and replace the cover inside the epub.

    Badge placement: 26% of cover width, top-right corner with 2.5% margin.
    Returns True if the badge was applied, False otherwise.
    """
    cover_src = source_dir / "cover.jpg"
    if not cover_src.exists():
        return False
    if not badge_path.exists():
        logger.warning("Badge introuvable : %s", badge_path)
        return False

    try:
        cover = PILImage.open(cover_src).convert("RGBA")
        badge = PILImage.open(badge_path).convert("RGBA")
        cw, ch = cover.size
        badge_w = int(cw * 0.26)
        badge_h = int(badge.height * badge_w / badge.width)
        badge = badge.resize((badge_w, badge_h), PILImage.LANCZOS)
        margin = int(cw * 0.025)
        result = cover.copy()
        result.paste(badge, (cw - badge_w - margin, margin), badge)
        buf = io.BytesIO()
        result.convert("RGB").save(buf, format="JPEG", quality=95)
        cover_bytes = buf.getvalue()
    except Exception as exc:
        logger.warning("Impossible de composer le badge sur la couverture : %s", exc)
        return False

    tmp = output_epub_path.with_suffix(".covtmp.epub")
    try:
        with zipfile.ZipFile(output_epub_path, "r") as zin:
            cover_zip_name = _find_cover_in_open_zip(zin)
            if cover_zip_name is None:
                logger.warning("Couverture introuvable dans l'epub — badge ignoré.")
                return False
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == "mimetype":
                        zout.writestr(zipfile.ZipInfo("mimetype"), data, compress_type=zipfile.ZIP_STORED)
                    elif info.filename == cover_zip_name:
                        zout.writestr(info, cover_bytes)
                    else:
                        zout.writestr(info, data)
        tmp.replace(output_epub_path)
    except Exception as exc:
        logger.warning("Échec de l'écriture du badge dans l'epub : %s", exc)
        tmp.unlink(missing_ok=True)
        return False

    logger.info("Badge IA appliqué sur la couverture (%s).", cover_zip_name)
    return True
