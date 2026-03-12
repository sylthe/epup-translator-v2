"""Phase 1: Literary analysis of the novel via Claude API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.models import AnalysisResult, Config, SpineItem
from src.prompt_builder import ANALYSIS_SECTIONS, PromptBuilder

logger = logging.getLogger(__name__)


def build_analysis_sample(
    spine_items: list[SpineItem],
    config: Config,
    client: ClaudeClient,
) -> str:
    """
    Build a representative text sample for analysis.

    Strategy (from spec):
    - Chapters 1–3 in full (establish tone, characters, style)
    - One middle chapter
    - Last chapter
    - Total capped at ~50 000 tokens
    """
    max_tokens = 50_000
    chapters = [item for item in spine_items if item.is_chapter]

    if not chapters:
        # Fallback: use all spine items
        chapters = spine_items

    selected_indices: list[int] = []
    nb = len(chapters)

    # First 3 chapters (indices 0, 1, 2)
    for i in config.analysis.sample_chapters:
        idx = i - 1  # convert 1-based to 0-based
        if 0 <= idx < nb:
            selected_indices.append(idx)

    # Middle chapter
    if config.analysis.include_middle and nb > 4:
        mid = nb // 2
        if mid not in selected_indices:
            selected_indices.append(mid)

    # Last chapter
    if config.analysis.include_last and nb > 1:
        last = nb - 1
        if last not in selected_indices:
            selected_indices.append(last)

    selected_indices = sorted(set(selected_indices))

    parts: list[str] = []
    total_tokens = 0

    for idx in selected_indices:
        chapter = chapters[idx]
        text = "\n".join(
            node.original_text
            for node in chapter.text_nodes
            if node.original_text.strip()
        )
        tokens = client.count_tokens(text)
        if total_tokens + tokens > max_tokens and parts:
            # Truncate this chapter to fit remaining budget
            remaining = max_tokens - total_tokens
            words = text.split()
            # rough estimate: 1 token ≈ 0.75 words
            word_limit = int(remaining * 0.75)
            text = " ".join(words[:word_limit])

        header = f"\n\n--- CHAPTER {idx + 1} ---\n\n"
        parts.append(header + text)
        total_tokens += client.count_tokens(text)

        if total_tokens >= max_tokens:
            break

    return "".join(parts)


def _parse_section_response(section_name: str, text: str) -> dict[str, Any]:
    """
    Parse JSON from a Claude response, handling Markdown code fences.

    Returns the parsed dict, or an empty dict with an 'error' key on failure.
    """
    # Strip markdown fences if present
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        return {"_raw": data}
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON for section %r: %s", section_name, exc)
        return {"error": str(exc), "_raw_text": text[:500]}


def _merge_analysis(results: dict[str, dict[str, Any]], book_id: str) -> AnalysisResult:
    """Merge per-section dicts into a single AnalysisResult."""

    def _get(key: str, default: Any = None) -> Any:
        for section_data in results.values():
            if key in section_data:
                return section_data[key]
        return default

    return AnalysisResult(
        book_id=book_id,
        identification=_get("identification", {}),
        structure_texte=_get("structure_texte", {}),
        cadre_narratif=_get("cadre_narratif", {}),
        ton_style=_get("ton_style", {}),
        personnages=[],  # will be populated below
        relations=[],
        registre_dialogues=_get("registre_dialogues", {}),
        glossaire=[],
        idiomes=[],
        contraintes_grammaticales=_get("contraintes_grammaticales", []),
        references_culturelles=[],
        themes=[],
        sensibilite_contenu=_get("sensibilite_contenu", {}),
        coherence_stylistique=_get("coherence_stylistique", {}),
        notes_traduction=_get("notes_traduction", []),
    )


_SECTION_LABELS: dict[str, str] = {
    "identification_et_structure": "Identification & structure",
    "cadre_narratif_et_style":     "Cadre narratif & style",
    "personnages_et_relations":    "Personnages & relations",
    "linguistique":                "Glossaire & idiomes",
    "culture_themes_sensibilite":  "Culture, thèmes & sensibilité",
    "coherence_et_notes":          "Cohérence & notes finales",
}


async def run_analysis(
    epub_content_or_sample: Any,
    client: ClaudeClient,
    prompt_builder: PromptBuilder,
    cache: CacheManager,
    config: Config,
    *,
    sample_text: str | None = None,
    console: Console | None = None,
) -> AnalysisResult:
    """
    Run the 6 sequential analysis API calls and return a merged AnalysisResult.

    If analysis is already cached, loads from cache instead.
    Displays a Rich progress bar when *console* is provided.
    """
    if cache.is_analysis_complete():
        logger.info("Loading analysis from cache")
        if console:
            console.print("  [dim]Analyse trouvée en cache — chargement.[/dim]")
        return cache.load_analysis()

    # Build sample if not provided
    if sample_text is None:
        if isinstance(epub_content_or_sample, str):
            sample_text = epub_content_or_sample
        else:
            if console:
                console.print("  Construction de l'échantillon…")
            sample_text = build_analysis_sample(
                epub_content_or_sample.spine_items, config, client
            )

    results: dict[str, dict[str, Any]] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Analyse", total=len(ANALYSIS_SECTIONS))

        for section in ANALYSIS_SECTIONS:
            name = section["name"]
            label = _SECTION_LABELS.get(name, name)
            progress.update(task, description=f"[cyan]{label}[/cyan]")
            logger.info("Analysing section: %s", name)

            system, user = prompt_builder.build_analysis_prompt(name, sample_text)
            response = await client.complete(system, user)
            parsed = _parse_section_response(name, response)
            results[name] = parsed

            progress.advance(task)

            if config.translation.batch_delay_seconds > 0:
                await asyncio.sleep(config.translation.batch_delay_seconds)

    book_id = (
        epub_content_or_sample.book_id
        if hasattr(epub_content_or_sample, "book_id")
        else "unknown"
    )
    analysis = _merge_analysis(results, book_id)
    cache.save_analysis(analysis)
    return analysis


def display_analysis_summary(analysis: AnalysisResult, console: Console) -> None:
    """Display a Rich table summarising the analysis for human validation."""
    table = Table(title="Résumé de l'analyse", show_header=True, header_style="bold cyan")
    table.add_column("Section", style="bold")
    table.add_column("Résumé")

    ident = analysis.identification
    if ident:
        table.add_row(
            "Identification",
            f"{ident.get('titre_original', '?')} — {ident.get('genre', '?')} ({ident.get('nb_chapitres', '?')} chapitres)",
        )

    cadre = analysis.cadre_narratif
    if cadre:
        table.add_row(
            "Cadre narratif",
            f"PDV: {cadre.get('point_de_vue', '?')} — Temps: {cadre.get('temps_narratif', '?')}",
        )

    ton = analysis.ton_style
    if ton:
        table.add_row(
            "Ton & style",
            f"Niveau: {ton.get('niveau_langue', '?')} — Rythme: {ton.get('rythme', '?')}",
        )

    nb_persos = len(analysis.personnages)
    table.add_row("Personnages", f"{nb_persos} personnage(s) identifié(s)")

    nb_glossaire = len(analysis.glossaire)
    nb_idiomes = len(analysis.idiomes)
    table.add_row("Linguistique", f"{nb_glossaire} terme(s) au glossaire, {nb_idiomes} idiome(s)")

    nb_refs = len(analysis.references_culturelles)
    table.add_row("Références culturelles", f"{nb_refs} référence(s) identifiée(s)")

    nb_notes = len(analysis.notes_traduction)
    table.add_row("Notes de traduction", f"{nb_notes} note(s)")

    console.print(table)
