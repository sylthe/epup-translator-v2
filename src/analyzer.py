"""Phase 1: Literary analysis of the novel via Claude API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from json_repair import repair_json

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

    Strategy: include ALL chapters in reading order up to the 50 000-token
    budget, truncating the last included chapter if needed.  This maximises
    character and plot coverage compared to a sparse selection.
    """
    max_tokens = 50_000
    chapters = [item for item in spine_items if item.is_chapter]

    if not chapters:
        chapters = spine_items

    parts: list[str] = []
    total_tokens = 0

    for idx, chapter in enumerate(chapters):
        text = "\n".join(
            node.original_text
            for node in chapter.text_nodes
            if node.original_text.strip()
        )
        if not text:
            continue

        tokens = client.count_tokens(text)
        remaining = max_tokens - total_tokens

        if tokens > remaining:
            if not parts:
                # First chapter alone exceeds budget — truncate it
                words = text.split()
                word_limit = int(remaining * 0.75)
                text = " ".join(words[:word_limit])
            else:
                break  # budget exhausted

        header = f"\n\n--- CHAPTER {idx + 1} ---\n\n"
        parts.append(header + text)
        total_tokens += client.count_tokens(text)

        if total_tokens >= max_tokens:
            break

    return "".join(parts)


def _extract_json_candidate(text: str) -> str:
    """
    Extract the most likely JSON object from a raw LLM response.

    Strategy (in order):
    1. Content inside a ```json ... ``` or ``` ... ``` fence
    2. Substring from the first '{' to the last '}'
    3. The original text stripped of leading/trailing whitespace
    """
    stripped = text.strip()

    # 1. Markdown fence
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        return fence.group(1).strip()

    # 2. First '{' … last '}'
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]

    return stripped


def _parse_section_response(section_name: str, text: str) -> dict[str, Any]:
    """
    Parse JSON from a Claude response using a cascade of strategies:

    1. Standard json.loads on the extracted candidate
    2. json_repair (handles trailing commas, single quotes, etc.)
    3. Return an error dict (section will be empty, not fatal)
    """
    candidate = _extract_json_candidate(text)

    # Strategy 1: strict parse
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: lenient repair
    try:
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            logger.info("JSON repaired for section %r", section_name)
            return repaired
    except Exception:
        pass

    logger.warning(
        "Could not parse JSON for section %r — section will be empty.\nRaw (first 300 chars): %s",
        section_name,
        text[:300],
    )
    return {}


def _as_list(value: Any) -> list[Any]:
    """Ensure a value is a plain list; wrap dicts in a list, return [] for None."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # API sometimes returns a nested dict instead of a list — flatten values
        flat: list[Any] = []
        for v in value.values():
            if isinstance(v, list):
                flat.extend(v)
        return flat
    return []


def _merge_analysis(results: dict[str, dict[str, Any]], book_id: str) -> AnalysisResult:
    """Merge per-section dicts into a single AnalysisResult."""

    def _get(key: str, default: Any = None) -> Any:
        for section_data in results.values():
            if key in section_data:
                return section_data[key]
        return default

    try:
        return AnalysisResult(
            book_id=book_id,
            identification=_get("identification", {}),
            structure_texte=_get("structure_texte", {}),
            cadre_narratif=_get("cadre_narratif", {}),
            ton_style=_get("ton_style", {}),
            personnages=_as_list(_get("personnages")),
            relations=_as_list(_get("relations")),
            registre_dialogues=_get("registre_dialogues", {}),
            glossaire=_as_list(_get("glossaire")),
            idiomes=_as_list(_get("idiomes")),
            contraintes_grammaticales=_as_list(_get("contraintes_grammaticales")),
            references_culturelles=_as_list(_get("references_culturelles")),
            themes=_as_list(_get("themes")),
            sensibilite_contenu=_get("sensibilite_contenu", {}),
            coherence_stylistique=_get("coherence_stylistique", {}),
            notes_traduction=_as_list(_get("notes_traduction")),
        )
    except Exception as exc:
        logger.warning("AnalysisResult validation error — some fields may be empty: %s", exc)
        return AnalysisResult(book_id=book_id)


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

            # Retry once if parsing returned empty (malformed JSON)
            if not parsed:
                progress.update(task, description=f"[yellow]{label} — nouvelle tentative…[/yellow]")
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
