"""Data models for epub-translator: dataclasses and Pydantic schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Dataclasses — in-memory ePub representation
# ---------------------------------------------------------------------------


@dataclass
class TextNode:
    """A single translatable text node extracted from an HTML document."""

    xpath: str
    """XPath-like address of this node in the HTML tree (e.g. 'body/div[2]/p[1]')."""
    original_text: str
    """Original English text."""
    translated_text: str | None = None
    """Will be filled by the translation phase."""
    parent_tag: str = "p"
    """Tag of the immediate parent element (e.g. 'p', 'h1', 'span')."""
    attributes: dict[str, Any] = field(default_factory=dict)
    """CSS classes and other attributes of the parent element."""


@dataclass
class SpineItem:
    """One document in the ePub spine (typically one chapter or front-matter file)."""

    id: str
    """Item ID as declared in the OPF spine."""
    filename: str
    """e.g. 'chapter01.xhtml'"""
    html_content: str
    """Raw HTML/XHTML content of the file."""
    text_nodes: list[TextNode] = field(default_factory=list)
    """Translatable text nodes extracted from the HTML."""
    is_chapter: bool = False
    """True when this item contains narrative content."""
    chapter_number: int | None = None
    """Sequential chapter index (0-based) among narrative items."""


@dataclass
class StyleSheet:
    """An embedded CSS file."""

    filename: str
    content: bytes


@dataclass
class Image:
    """An embedded image."""

    filename: str
    media_type: str
    content: bytes


@dataclass
class Font:
    """An embedded font file."""

    filename: str
    media_type: str
    content: bytes


@dataclass
class TocEntry:
    """One entry in the table of contents."""

    title: str
    href: str
    level: int = 0
    children: list[TocEntry] = field(default_factory=list)


@dataclass
class EpubContent:
    """Complete in-memory representation of an extracted ePub."""

    book_id: str
    """SHA-256 of the original ePub file (hex string)."""
    metadata: dict[str, Any]
    """OPF metadata (title, author, language, …)."""
    spine_items: list[SpineItem]
    """Documents in reading order."""
    styles: list[StyleSheet] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    fonts: list[Font] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pydantic models — API contracts and persisted state
# ---------------------------------------------------------------------------


class TranslatedNode(BaseModel):
    index: int
    original: str = ""   # no longer required in API response — kept for backward compat
    translated: str


class TranslationResult(BaseModel):
    translated_nodes: list[TranslatedNode]
    translation_notes: list[str] = Field(default_factory=list)


class PersonnageModel(BaseModel):
    nom: str
    genre: str = ""
    age: str = ""
    role_narratif: str = ""
    personnalite: str = ""
    style_parole: str = ""
    particularites_linguistiques: list[str] = Field(default_factory=list)
    exemples_dialogue: list[dict[str, str]] = Field(default_factory=list)


class RelationModel(BaseModel):
    personnages: list[str]
    relation: str = ""
    registre: str = "tu"
    evolution_registre: str | None = None
    termes_affectifs: list[str] = Field(default_factory=list)
    surnoms: list[str] = Field(default_factory=list)


class GlossaireTerme(BaseModel):
    en: str = ""
    fr: str = ""
    contexte: str = ""


class IdiomeModel(BaseModel):
    expression: str
    sens: str = ""
    traduction: str = ""


class ReferenceCulturelle(BaseModel):
    element: str
    type: str = ""
    decision: str = ""


class ThemeModel(BaseModel):
    theme: str
    importance: str = ""


class ExpressionRecurrente(BaseModel):
    en: str
    fr: str


class AnalysisResult(BaseModel):
    """Complete structured analysis produced by Phase 1."""

    book_id: str
    analysis_date: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Section 1 + 10
    identification: dict[str, Any] = Field(default_factory=dict)
    structure_texte: dict[str, Any] = Field(default_factory=dict)

    # Section 2 + 3
    cadre_narratif: dict[str, Any] = Field(default_factory=dict)
    ton_style: dict[str, Any] = Field(default_factory=dict)

    # Section 4 + 5 + 6
    personnages: list[PersonnageModel] = Field(default_factory=list)
    relations: list[RelationModel] = Field(default_factory=list)
    registre_dialogues: dict[str, Any] = Field(default_factory=dict)

    # Section 7 + 8 + 11
    glossaire: list[GlossaireTerme] = Field(default_factory=list)
    idiomes: list[IdiomeModel] = Field(default_factory=list)
    contraintes_grammaticales: list[dict[str, Any]] = Field(default_factory=list)

    # Section 9 + 13 + 14
    references_culturelles: list[ReferenceCulturelle] = Field(default_factory=list)
    themes: list[ThemeModel] = Field(default_factory=list)
    sensibilite_contenu: dict[str, Any] = Field(default_factory=dict)

    # Section 12 + 15
    coherence_stylistique: dict[str, Any] = Field(default_factory=dict)
    notes_traduction: list[str] = Field(default_factory=list)


class ApiConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"
    analysis_model: str = "claude-haiku-4-5-20251001"
    max_tokens_response: int = 16000
    temperature: float = 0.3


class TranslationConfig(BaseModel):
    max_tokens_per_segment: int = 8000
    overlap_paragraphs: int = 3
    batch_delay_seconds: float = 1.0


class AnalysisConfig(BaseModel):
    sample_chapters: list[int] = Field(default_factory=lambda: [1, 2, 3])
    include_middle: bool = True
    include_last: bool = True


class OutputConfig(BaseModel):
    cache_dir: Path = Path("./output/cache")
    analysis_dir: Path = Path("./output/analysis")
    translated_dir: Path = Path("./output/translated")


class Config(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


class ChapterCacheEntry(BaseModel):
    chapter_number: int
    filename: str
    text_nodes: list[dict[str, Any]]
    """Serialised TextNode list (original + translated)."""
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CacheState(BaseModel):
    book_id: str
    analysis_complete: bool = False
    completed_chapters: list[int] = Field(default_factory=list)
    """Sorted list of completed chapter numbers (0-based)."""
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
