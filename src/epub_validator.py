"""ePub validation and auto-correction (structure, metadata, TOC, CSS, images)."""

from __future__ import annotations

import posixpath
import re
import uuid
import warnings
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------------------------------------------------------------
# XML namespace constants
# ---------------------------------------------------------------------------

_OPF_NS       = "http://www.idpf.org/2007/opf"
_DC_NS        = "http://purl.org/dc/elements/1.1/"
_NCX_NS       = "http://www.daisy.org/z3986/2005/ncx/"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

_MIMETYPE_VALUE = b"application/epub+zip"

# Minimal BCP 47 validation: "en", "fr", "en-US", "zh-Hant-TW"
_BCP47_RE = re.compile(r"^[a-zA-Z]{2,8}(-[a-zA-Z0-9]{1,8})*$")

# Heuristic: filenames containing these substrings are NOT narrative chapters
_NON_CHAPTER_HINTS = {
    "cover", "toc", "nav", "ncx", "copyright", "dedication",
    "title", "colophon", "about", "appendix", "index", "halftitle",
}


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    severity: Literal["error", "warning", "info"]
    category: str   # structure | metadata | manifest | spine | toc | css | images
    message: str
    fixable: bool = False
    fix_description: str = ""
    # Internal: raw href as written in OPF (for orphan removal regex)
    _raw_href: str = field(default="", repr=False, compare=False)


@dataclass
class ValidationReport:
    epub_path: Path
    issues: list[ValidationIssue] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience views
    # ------------------------------------------------------------------

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "info"]

    @property
    def fixable_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.fixable]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def _add(
        self,
        severity: Literal["error", "warning", "info"],
        category: str,
        message: str,
        *,
        fixable: bool = False,
        fix_description: str = "",
        raw_href: str = "",
    ) -> None:
        self.issues.append(
            ValidationIssue(severity, category, message, fixable, fix_description, raw_href)
        )


# ---------------------------------------------------------------------------
# Internal parsed-state container (shared across check functions)
# ---------------------------------------------------------------------------

@dataclass
class _ParsedEpub:
    names: set[str]
    opf_path: str | None = None
    opf_dir: str = ""
    opf_tree: ET.Element | None = None
    # item_id → canonical zip path
    manifest_map: dict[str, str] = field(default_factory=dict)
    spine_idrefs: list[str] = field(default_factory=list)
    ncx_path: str | None = None
    nav_path: str | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _base_dir(zip_entry: str) -> str:
    """Directory of a zip entry path without trailing slash.
    'OEBPS/content.opf' → 'OEBPS';  'content.opf' → ''
    """
    parent = str(PurePosixPath(zip_entry).parent)
    return "" if parent == "." else parent


def _resolve_href(href: str, base_dir: str, names: set[str]) -> str | None:
    """Resolve a relative href to a canonical zip entry name.

    Strips fragment identifiers, handles relative paths (including '..'),
    and strips leading slashes from malformed absolute hrefs.
    Returns None if the resolved path is not in the ZIP.
    """
    href = href.split("#")[0].strip()
    if not href:
        return None  # pure fragment — no file to check

    href = href.lstrip("/")

    if base_dir:
        resolved = posixpath.normpath(f"{base_dir}/{href}")
    else:
        resolved = posixpath.normpath(href)

    return resolved if resolved in names else None


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_mimetype(z: zipfile.ZipFile, names: set[str], report: ValidationReport) -> None:
    if "mimetype" not in names:
        report._add(
            "error", "structure", "Fichier 'mimetype' manquant",
            fixable=True, fix_description="Création du fichier mimetype",
        )
        return

    info = z.getinfo("mimetype")
    if info.compress_type != zipfile.ZIP_STORED:
        report._add(
            "warning", "structure",
            "Fichier 'mimetype' compressé — doit être non-compressé (spec EPUB §3.3)",
            fixable=True, fix_description="Réécriture en mode non-compressé",
        )

    content = z.read("mimetype").strip()
    if content != _MIMETYPE_VALUE:
        report._add(
            "error", "structure",
            f"Contenu 'mimetype' incorrect : « {content.decode(errors='replace')} » "
            f"(attendu : application/epub+zip)",
            fixable=True, fix_description="Correction du contenu mimetype",
        )
    else:
        report._add("info", "structure", "mimetype : présent et correct")


def _check_container(
    z: zipfile.ZipFile, names: set[str], parsed: _ParsedEpub, report: ValidationReport
) -> None:
    if "META-INF/container.xml" not in names:
        report._add("error", "structure", "META-INF/container.xml manquant")
        return

    try:
        root = ET.fromstring(z.read("META-INF/container.xml"))
    except ET.ParseError as exc:
        report._add("error", "structure", f"META-INF/container.xml invalide (XML malformé) : {exc}")
        return

    rootfile = root.find(f".//{{{_CONTAINER_NS}}}rootfile")
    if rootfile is None:
        rootfile = root.find(".//rootfile")
    if rootfile is None:
        report._add("error", "structure", "Aucun élément <rootfile> dans container.xml")
        return

    opf_path = rootfile.get("full-path", "").strip()
    if not opf_path:
        report._add("error", "structure", "Attribut full-path manquant dans <rootfile>")
        return

    if opf_path not in names:
        report._add("error", "structure", f"Fichier OPF référencé introuvable dans le ZIP : {opf_path}")
        return

    parsed.opf_path = opf_path
    parsed.opf_dir = _base_dir(opf_path)
    report._add("info", "structure", f"container.xml valide → OPF : {opf_path}")


def _check_opf(z: zipfile.ZipFile, parsed: _ParsedEpub, report: ValidationReport) -> None:
    assert parsed.opf_path is not None
    try:
        parsed.opf_tree = ET.fromstring(z.read(parsed.opf_path))
        report._add("info", "structure", "Fichier OPF valide (XML bien formé)")
    except ET.ParseError as exc:
        report._add("error", "structure", f"Fichier OPF invalide (XML malformé) : {exc}")


def _check_manifest(z: zipfile.ZipFile, parsed: _ParsedEpub, report: ValidationReport) -> None:
    assert parsed.opf_tree is not None
    missing: list[str] = []

    for item in parsed.opf_tree.iter(f"{{{_OPF_NS}}}item"):
        item_id  = item.get("id", "?")
        href     = item.get("href", "")
        media    = item.get("media-type", "")
        props    = item.get("properties", "")

        resolved = _resolve_href(href, parsed.opf_dir, parsed.names)
        if resolved is None:
            missing.append(href)
            report._add(
                "error", "manifest",
                f"Fichier manifest introuvable dans le ZIP : {href}  (id={item_id})",
                fixable=True,
                fix_description=f"Suppression de l'entrée manifest orpheline (id={item_id})",
                raw_href=href,
            )
        else:
            parsed.manifest_map[item_id] = resolved
            # Detect NCX and nav
            if media == "application/x-dtbncx+xml":
                parsed.ncx_path = resolved
            if "nav" in props and "html" in media:
                parsed.nav_path = resolved

    # Also detect NCX via spine toc attribute
    spine = parsed.opf_tree.find(f"{{{_OPF_NS}}}spine")
    if spine is not None:
        toc_id = spine.get("toc", "")
        if toc_id and toc_id in parsed.manifest_map and parsed.ncx_path is None:
            parsed.ncx_path = parsed.manifest_map[toc_id]

    if not missing:
        report._add("info", "manifest", f"Manifest : {len(parsed.manifest_map)} fichier(s), tous présents")


def _check_spine(parsed: _ParsedEpub, report: ValidationReport) -> None:
    assert parsed.opf_tree is not None
    spine = parsed.opf_tree.find(f"{{{_OPF_NS}}}spine")
    if spine is None:
        report._add("error", "spine", "Élément <spine> manquant dans l'OPF")
        return

    broken: list[str] = []
    for itemref in spine.iter(f"{{{_OPF_NS}}}itemref"):
        idref = itemref.get("idref", "")
        parsed.spine_idrefs.append(idref)
        if idref not in parsed.manifest_map:
            broken.append(idref)

    if broken:
        report._add(
            "error", "spine",
            f"Spine : {len(broken)} idref(s) sans entrée manifest correspondante : "
            + ", ".join(broken[:5]) + ("…" if len(broken) > 5 else ""),
        )
    else:
        report._add("info", "spine", f"Spine : {len(parsed.spine_idrefs)} item(s), tous valides")


def _check_metadata(parsed: _ParsedEpub, report: ValidationReport) -> None:
    assert parsed.opf_tree is not None
    metadata = parsed.opf_tree.find(f"{{{_OPF_NS}}}metadata")
    if metadata is None:
        # Fallback: try without namespace
        metadata = parsed.opf_tree.find("metadata")
    if metadata is None:
        report._add("error", "metadata", "Élément <metadata> manquant dans l'OPF")
        return

    def _dc(tag: str) -> str | None:
        el = metadata.find(f"{{{_DC_NS}}}{tag}")
        if el is None:
            el = metadata.find(tag)
        return (el.text or "").strip() if el is not None else None

    title = _dc("title")
    if title:
        report._add("info", "metadata", f"Titre : {title}")
    else:
        report._add("warning", "metadata", "dc:title manquant")

    creator = _dc("creator")
    if not creator:
        report._add("warning", "metadata", "dc:creator (auteur) manquant")

    lang = _dc("language")
    if not lang:
        report._add(
            "error", "metadata", "dc:language manquant",
            fixable=True, fix_description="Ajout de dc:language='en'",
        )
    elif not _BCP47_RE.match(lang):
        report._add(
            "warning", "metadata",
            f"dc:language « {lang} » ne semble pas conforme BCP 47 (ex: 'en', 'fr', 'en-US')",
        )
    else:
        report._add("info", "metadata", f"Langue : {lang}")

    identifier = _dc("identifier")
    if not identifier:
        report._add(
            "error", "metadata", "dc:identifier manquant (ISBN, UUID, etc.)",
            fixable=True, fix_description="Ajout d'un UUID comme dc:identifier",
        )
    else:
        report._add("info", "metadata", f"Identifiant : {identifier}")


def _check_toc(z: zipfile.ZipFile, parsed: _ParsedEpub, report: ValidationReport) -> None:
    if parsed.ncx_path is None and parsed.nav_path is None:
        report._add("error", "toc", "Table des matières introuvable (ni NCX ni nav.xhtml)")
        return

    toc_files: set[str] = set()

    if parsed.ncx_path:
        _check_ncx(z, parsed.ncx_path, parsed.names, report, toc_files)

    if parsed.nav_path:
        _check_nav(z, parsed.nav_path, parsed.names, report, toc_files)

    # Check coverage: do all chapter spine items have at least one TOC entry?
    if toc_files:
        uncovered: list[str] = []
        for idref in parsed.spine_idrefs:
            path = parsed.manifest_map.get(idref, "")
            if not path:
                continue
            name = Path(path).name.lower()
            if any(hint in name for hint in _NON_CHAPTER_HINTS):
                continue  # skip non-narrative items
            if path not in toc_files:
                uncovered.append(Path(path).name)

        if uncovered:
            report._add(
                "warning", "toc",
                f"{len(uncovered)} chapitre(s) absent(s) de la table des matières : "
                + ", ".join(uncovered[:5]) + ("…" if len(uncovered) > 5 else ""),
            )
        else:
            report._add("info", "toc", "Tous les chapitres sont représentés dans la TOC")


def _check_ncx(
    z: zipfile.ZipFile,
    ncx_path: str,
    names: set[str],
    report: ValidationReport,
    toc_files: set[str],
) -> None:
    try:
        root = ET.fromstring(z.read(ncx_path))
    except ET.ParseError as exc:
        report._add("error", "toc", f"NCX invalide (XML malformé) : {exc}")
        return

    ncx_dir = _base_dir(ncx_path)
    broken: list[str] = []

    for content in root.iter(f"{{{_NCX_NS}}}content"):
        src = content.get("src", "")
        resolved = _resolve_href(src, ncx_dir, names)
        if resolved is None:
            broken.append(src.split("#")[0])
        else:
            toc_files.add(resolved)

    if broken:
        report._add(
            "error", "toc",
            f"NCX : {len(broken)} entrée(s) pointent vers des fichiers inexistants : "
            + ", ".join(dict.fromkeys(broken[:5])) + ("…" if len(broken) > 5 else ""),
        )
    else:
        nav_count = len(list(root.iter(f"{{{_NCX_NS}}}navPoint")))
        report._add("info", "toc", f"NCX : {nav_count} entrée(s), toutes valides")


def _check_nav(
    z: zipfile.ZipFile,
    nav_path: str,
    names: set[str],
    report: ValidationReport,
    toc_files: set[str],
) -> None:
    try:
        soup = BeautifulSoup(z.read(nav_path), "lxml")
    except Exception as exc:
        report._add("error", "toc", f"nav.xhtml illisible : {exc}")
        return

    nav_dir = _base_dir(nav_path)
    broken: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        resolved = _resolve_href(href, nav_dir, names)
        if resolved is None:
            raw = href.split("#")[0]
            if raw:
                broken.append(raw)
        else:
            toc_files.add(resolved)

    if broken:
        report._add(
            "warning", "toc",
            f"nav.xhtml : {len(broken)} lien(s) vers des fichiers inexistants : "
            + ", ".join(dict.fromkeys(broken[:5])) + ("…" if len(broken) > 5 else ""),
        )
    else:
        link_count = len(soup.find_all("a", href=True))
        report._add("info", "toc", f"nav.xhtml : {link_count} lien(s), tous valides")


def _check_css_links(z: zipfile.ZipFile, parsed: _ParsedEpub, report: ValidationReport) -> None:
    broken: list[str] = []

    for idref in parsed.spine_idrefs:
        html_path = parsed.manifest_map.get(idref)
        if not html_path:
            continue
        html_dir = _base_dir(html_path)
        try:
            soup = BeautifulSoup(z.read(html_path), "lxml")
        except Exception:
            continue

        for link in soup.find_all("link"):
            rel = link.get("rel") or []
            if isinstance(rel, list):
                rel = " ".join(rel)
            if "stylesheet" not in rel.lower():
                continue
            href = link.get("href", "")
            if not href or href.startswith(("http://", "https://")):
                continue
            if _resolve_href(href, html_dir, parsed.names) is None:
                broken.append(f"{Path(html_path).name} → {href}")

    if broken:
        report._add(
            "error", "css",
            f"{len(broken)} référence(s) CSS introuvable(s) : "
            + " | ".join(broken[:5]) + ("…" if len(broken) > 5 else ""),
        )
    else:
        report._add("info", "css", "Toutes les feuilles de style CSS sont présentes")


def _check_image_refs(z: zipfile.ZipFile, parsed: _ParsedEpub, report: ValidationReport) -> None:
    broken: list[str] = []

    for idref in parsed.spine_idrefs:
        html_path = parsed.manifest_map.get(idref)
        if not html_path:
            continue
        html_dir = _base_dir(html_path)
        try:
            soup = BeautifulSoup(z.read(html_path), "lxml")
        except Exception:
            continue

        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src or src.startswith(("http://", "https://")):
                continue
            if _resolve_href(src, html_dir, parsed.names) is None:
                broken.append(f"{Path(html_path).name} → {src}")

        # EPUB3 SVG <image xlink:href="...">
        for image in soup.find_all("image"):
            src = image.get("xlink:href") or image.get("href", "")
            if not src or src.startswith(("http://", "https://")):
                continue
            if _resolve_href(src, html_dir, parsed.names) is None:
                broken.append(f"{Path(html_path).name} → {src}")

    if broken:
        report._add(
            "warning", "images",
            f"{len(broken)} image(s) introuvable(s) : "
            + " | ".join(broken[:5]) + ("…" if len(broken) > 5 else ""),
        )
    else:
        report._add("info", "images", "Toutes les images référencées sont présentes")


# ---------------------------------------------------------------------------
# Public API — validate
# ---------------------------------------------------------------------------

def validate_epub(epub_path: Path) -> ValidationReport:
    """Run all validation checks and return a report."""
    report = ValidationReport(epub_path=epub_path)

    if not zipfile.is_zipfile(epub_path):
        report._add("error", "structure", "Fichier non lisible comme ZIP — epub corrompu")
        return report

    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            names = set(z.namelist())
            parsed = _ParsedEpub(names=names)

            _check_mimetype(z, names, report)
            _check_container(z, names, parsed, report)

            if parsed.opf_path is None:
                return report

            _check_opf(z, parsed, report)
            if parsed.opf_tree is None:
                return report

            _check_manifest(z, parsed, report)
            _check_spine(parsed, report)
            _check_metadata(parsed, report)
            _check_toc(z, parsed, report)
            _check_css_links(z, parsed, report)
            _check_image_refs(z, parsed, report)

    except zipfile.BadZipFile as exc:
        report._add("error", "structure", f"ZIP corrompu : {exc}")

    return report


# ---------------------------------------------------------------------------
# Public API — fix
# ---------------------------------------------------------------------------

def apply_fixes(report: ValidationReport, output_path: Path) -> int:
    """Apply all auto-fixable corrections and write the corrected ePub.

    Returns the number of distinct fixes applied.
    """
    epub_path = report.epub_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".fixmp.epub")

    # Collect orphan hrefs (raw values from the OPF) to remove from manifest
    orphan_hrefs: set[str] = {
        issue._raw_href
        for issue in report.issues
        if issue.fixable and issue.category == "manifest" and issue._raw_href
    }
    need_mimetype_fix = any(
        i.fixable and i.category == "structure" for i in report.issues
    )
    need_lang_fix = any(
        i.fixable and i.category == "metadata" and "language" in i.message.lower()
        for i in report.issues
    )
    need_id_fix = any(
        i.fixable and i.category == "metadata" and "identifier" in i.message.lower()
        for i in report.issues
    )

    fixes_applied = 0
    opf_path = _get_opf_path(epub_path)

    with zipfile.ZipFile(epub_path, "r") as zin, \
         zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:

        # --- Always write mimetype first, uncompressed ---
        if need_mimetype_fix:
            fixes_applied += 1
        zout.writestr(
            zipfile.ZipInfo("mimetype"),
            _MIMETYPE_VALUE,
            compress_type=zipfile.ZIP_STORED,
        )

        for info in zin.infolist():
            if info.filename == "mimetype":
                continue

            data = zin.read(info.filename)

            if info.filename == opf_path:
                data, n = _fix_opf_bytes(data, orphan_hrefs, need_lang_fix, need_id_fix)
                fixes_applied += n

            zout.writestr(info, data)

    tmp.replace(output_path)
    return fixes_applied


def _get_opf_path(epub_path: Path) -> str | None:
    """Return the OPF zip entry path, or None if not determinable."""
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            names = set(z.namelist())
            if "META-INF/container.xml" not in names:
                return None
            root = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = root.find(f".//{{{_CONTAINER_NS}}}rootfile")
            if rootfile is None:
                rootfile = root.find(".//rootfile")
            if rootfile is None:
                return None
            path = rootfile.get("full-path", "")
            return path if path in names else None
    except Exception:
        return None


def _fix_opf_bytes(
    opf_bytes: bytes,
    orphan_hrefs: set[str],
    add_language: bool,
    add_identifier: bool,
) -> tuple[bytes, int]:
    """Apply OPF patches and return (patched_bytes, number_of_fixes)."""
    text = opf_bytes.decode("utf-8", errors="replace")
    fixes = 0

    # Remove orphan manifest items: <item ... href="ORPHAN" ... />
    for href in orphan_hrefs:
        escaped = re.escape(href)
        # Match self-closing <item> with this href anywhere in its attributes
        new_text = re.sub(
            rf'<item\b[^>]*\bhref="{escaped}"[^>]*/>\n?',
            "",
            text,
        )
        if new_text != text:
            text = new_text
            fixes += 1

    if add_language:
        text = re.sub(
            r"(</metadata>)",
            "  <dc:language>en</dc:language>\n  \\1",
            text,
            count=1,
        )
        fixes += 1

    if add_identifier:
        uid = str(uuid.uuid4())
        text = re.sub(
            r"(</metadata>)",
            f'  <dc:identifier id="uid-fix">urn:uuid:{uid}</dc:identifier>\n  \\1',
            text,
            count=1,
        )
        fixes += 1

    return text.encode("utf-8"), fixes
