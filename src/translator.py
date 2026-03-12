"""Phase 2: Chapter-by-chapter translation via Claude API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from json_repair import repair_json

from rich.progress import Progress, TaskID

from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.models import AnalysisResult, Config, SpineItem, TextNode, TranslationResult
from src.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


def split_chapter_into_segments(
    text_nodes: list[TextNode],
    max_tokens: int,
    client: ClaudeClient,
) -> list[list[TextNode]]:
    """
    Split a chapter's text nodes into segments that fit within max_tokens.

    Cuts between paragraphs — never mid-paragraph.
    Returns a list of segments (each segment is a list of TextNode).
    """
    if not text_nodes:
        return []

    segments: list[list[TextNode]] = []
    current: list[TextNode] = []
    current_tokens = 0

    for node in text_nodes:
        node_tokens = client.count_tokens(node.original_text)
        # If a single node exceeds the limit, it must go in its own segment
        if node_tokens > max_tokens:
            if current:
                segments.append(current)
                current = []
                current_tokens = 0
            segments.append([node])
            continue

        if current and current_tokens + node_tokens > max_tokens:
            segments.append(current)
            current = []
            current_tokens = 0

        current.append(node)
        current_tokens += node_tokens

    if current:
        segments.append(current)

    return segments


def get_segment_context(
    segment_idx: int,
    segments: list[list[TextNode]],
    overlap: int = 3,
) -> str:
    """
    Build context string from the last *overlap* translated paragraphs
    of the previous segment.

    Returns empty string for the first segment.
    """
    if segment_idx == 0:
        return ""

    prev_segment = segments[segment_idx - 1]
    # Take the last `overlap` nodes that have been translated
    context_nodes = [n for n in prev_segment if n.translated_text][-overlap:]
    if not context_nodes:
        return ""

    lines = [f"[{n.parent_tag}] {n.translated_text}" for n in context_nodes]
    return "Fin du segment précédent (pour la continuité) :\n" + "\n".join(lines)


def _extract_json_candidate(text: str) -> str:
    """Extract the most likely JSON object from a raw LLM response."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        return fence.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _parse_translation_response(text: str) -> TranslationResult:
    """
    Parse JSON from Claude's translation response using a cascade:
    1. Standard json.loads
    2. json_repair (handles trailing commas, single quotes, etc.)
    3. Empty result (non-fatal — segment will have no translations)
    """
    candidate = _extract_json_candidate(text)

    # Strategy 1: strict
    try:
        data = json.loads(candidate)
        return TranslationResult(**data)
    except Exception:
        pass

    # Strategy 2: repair
    try:
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            logger.info("Translation JSON repaired")
            return TranslationResult(**repaired)
    except Exception:
        pass

    logger.warning("Could not parse translation response — segment skipped.\nRaw (first 300): %s", text[:300])
    return TranslationResult(translated_nodes=[], translation_notes=["Parse error — segment skipped"])


async def translate_segment(
    segment: list[TextNode],
    analysis: AnalysisResult,
    chapter_info: SpineItem,
    segment_idx: int,
    segments: list[list[TextNode]],
    client: ClaudeClient,
    prompt_builder: PromptBuilder,
    config: Config,
) -> TranslationResult:
    """
    Translate one segment (list of TextNodes) and return the TranslationResult.
    """
    system_prompt = prompt_builder.build_translation_system_prompt(analysis)

    # Build chapter context
    chapter_title = chapter_info.filename
    ident = analysis.identification
    if isinstance(ident, dict) and ident.get("titre_original"):
        pass  # chapter title from filename is fine

    context = get_segment_context(segment_idx, segments, config.translation.overlap_paragraphs)

    user_prompt = prompt_builder.build_chapter_prompt(
        chapter_number=(chapter_info.chapter_number or 0) + 1,
        chapter_title=chapter_title,
        text_nodes=segment,
        segment_context=context,
    )

    response = await client.complete(system_prompt, user_prompt)
    return _parse_translation_response(response)


def apply_translations(
    text_nodes: list[TextNode],
    result: TranslationResult,
) -> None:
    """
    Write translated text back into the TextNode objects.

    Matches by node index within the segment.
    """
    node_map = {i: node for i, node in enumerate(text_nodes)}

    for translated in result.translated_nodes:
        idx = translated.index
        if idx in node_map:
            node_map[idx].translated_text = translated.translated
        else:
            logger.warning("Translation index %d out of range (segment has %d nodes)", idx, len(text_nodes))


async def translate_chapter(
    chapter: SpineItem,
    analysis: AnalysisResult,
    client: ClaudeClient,
    prompt_builder: PromptBuilder,
    cache: CacheManager,
    config: Config,
    progress: Progress | None = None,
    progress_task: TaskID | None = None,
) -> SpineItem:
    """
    Translate all text nodes of a chapter, segment by segment.

    Saves the result to cache after completion.
    Returns the chapter with translated_text populated on all nodes.
    """
    chapter_num = chapter.chapter_number or 0

    if cache.is_chapter_complete(chapter_num):
        logger.info("Chapter %d already cached — loading", chapter_num)
        chapter.text_nodes = cache.load_chapter_result(chapter_num)
        return chapter

    segments = split_chapter_into_segments(
        chapter.text_nodes,
        config.translation.max_tokens_per_segment,
        client,
    )

    logger.info(
        "Translating chapter %d (%s): %d segment(s)",
        chapter_num,
        chapter.filename,
        len(segments),
    )

    n_segments = len(segments)
    for seg_idx, segment in enumerate(segments):
        if progress is not None and progress_task is not None and n_segments > 1:
            chap_label = f"[cyan]Chapitre {chapter_num + 1}[/cyan] — segment {seg_idx + 1}/{n_segments}"
            progress.update(progress_task, description=chap_label)

        result = await translate_segment(
            segment=segment,
            analysis=analysis,
            chapter_info=chapter,
            segment_idx=seg_idx,
            segments=segments,
            client=client,
            prompt_builder=prompt_builder,
            config=config,
        )
        apply_translations(segment, result)

        if result.translation_notes:
            for note in result.translation_notes:
                logger.debug("Translation note [ch%d seg%d]: %s", chapter_num, seg_idx, note)

    cache.save_chapter_result(chapter_num, chapter.text_nodes)
    return chapter
