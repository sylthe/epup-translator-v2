"""CLI entry point for epub-translator."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from src.analyzer import display_analysis_summary, run_analysis
from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.epub_handler import (
    apply_cover_badge,
    classify_nonchapter_item,
    extract_epub,
    extract_item_title,
    reconstruct_epub,
)
from src.epub_validator import ValidationReport, apply_fixes, validate_epub
from src.models import Config, SpineItem
from src.prompt_builder import PromptBuilder
from src.translator import translate_chapter
from src.utils import load_config

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """Traducteur de romans ePub EN→FR avec analyse professionnelle."""


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=verbose,
                markup=False,
            )
        ],
    )


@cli.command()
@click.argument("epub_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output ePub path.")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="config.yaml", show_default=True, help="Config YAML file.")
@click.option("--analysis-only", is_flag=True, default=False, help="Run analysis only, do not translate.")
@click.option("--resume", is_flag=True, default=False, help="Resume an interrupted translation.")
@click.option("--skip-analysis", is_flag=True, default=False, help="Skip analysis, use cached result.")
@click.option("--prompts-dir", type=click.Path(path_type=Path), default="prompts", show_default=True, help="Directory containing prompt templates.")
@click.option("--retranslate", "-r", default=None, help="Retranslate a specific chapter (by number, title, HTML file, or cache file).")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
def translate(
    epub_path: Path,
    output: Path | None,
    config_path: Path,
    analysis_only: bool,
    resume: bool,
    skip_analysis: bool,
    prompts_dir: Path,
    retranslate: str | None,
    verbose: bool,
) -> None:
    """Traduit un roman ePub de l'anglais au français."""
    _setup_logging(verbose)
    config = load_config(config_path)
    asyncio.run(
        run_translation(
            epub_path=epub_path,
            output=output,
            config=config,
            analysis_only=analysis_only,
            resume=resume,
            skip_analysis=skip_analysis,
            prompts_dir=prompts_dir,
            retranslate=retranslate,
        )
    )


@cli.command("clear-cache")
@click.argument("epub_path", type=click.Path(exists=True, path_type=Path))
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="config.yaml", show_default=True, help="Config YAML file.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
def clear_cache(epub_path: Path, config_path: Path, yes: bool, verbose: bool) -> None:
    """Supprime le cache (analyse + chapitres) pour un ePub donné."""
    _setup_logging(verbose)
    config = load_config(config_path)
    epub_content = extract_epub(epub_path)
    cache = CacheManager(
        epub_content.book_id,
        config.output.cache_dir,
        analysis_dir=config.output.analysis_dir,
    )
    console.print(f"  Livre  : [cyan]{epub_content.metadata.get('title', epub_path.name)}[/cyan]")
    console.print(f"  book_id: [dim]{epub_content.book_id}[/dim]")
    if not yes and not click.confirm("Supprimer le cache pour ce livre ?"):
        console.print("Annulé.")
        return
    cache.reset()
    console.print("[green]Cache supprimé.[/green]")


@cli.command()
@click.argument("epub_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Chemin du fichier corrigé (défaut: <nom>_fixed.epub).")
@click.option("--no-fix", is_flag=True, default=False,
              help="Rapport uniquement, sans générer de fichier corrigé.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
def validate(epub_path: Path, output: Path | None, no_fix: bool, verbose: bool) -> None:
    """Valide la structure d'un ePub et corrige les problèmes détectables."""
    _setup_logging(verbose)

    console.rule("[bold]Validation du ePub[/bold]")
    report = validate_epub(epub_path)
    _display_validation_report(report)

    fixable = report.fixable_issues
    if fixable and not no_fix:
        if output is None:
            output = epub_path.parent / f"{epub_path.stem}_fixed.epub"
        n = apply_fixes(report, output)
        console.print(f"\n[green]{n} correction(s) appliquée(s) → {output}[/green]")
    elif fixable and no_fix:
        console.print(
            f"\n[yellow]{len(fixable)} problème(s) corrigible(s) "
            f"(relancez sans --no-fix pour générer le fichier corrigé).[/yellow]"
        )
    elif not fixable and report.is_valid:
        console.print("\n[green]Aucun problème détecté.[/green]")

    sys.exit(0 if report.is_valid else 1)


def _display_validation_report(report: ValidationReport) -> None:
    """Display validation results grouped by category."""
    _ICONS = {
        "error":   "[red]✗[/red]",
        "warning": "[yellow]⚠[/yellow]",
        "info":    "[green]✓[/green]",
    }
    _CATEGORY_LABELS = {
        "structure": "Structure ZIP / container",
        "metadata":  "Métadonnées OPF",
        "manifest":  "Manifest",
        "spine":     "Spine",
        "toc":       "Table des matières",
        "css":       "Feuilles de style CSS",
        "images":    "Images",
    }

    # Group issues by category, preserving declaration order
    categories: dict[str, list] = {}
    for issue in report.issues:
        categories.setdefault(issue.category, []).append(issue)

    for category, issues in categories.items():
        label = _CATEGORY_LABELS.get(category, category.upper())
        console.rule(f"[bold]{label}[/bold]", style="dim")
        tbl = Table(show_header=False, box=None, padding=(0, 1))
        tbl.add_column("icon", no_wrap=True, min_width=3)
        tbl.add_column("message")
        tbl.add_column("fix", style="dim")
        for issue in issues:
            fix_str = f"→ {issue.fix_description}" if issue.fix_description else ""
            tbl.add_row(_ICONS[issue.severity], issue.message, fix_str)
        console.print(tbl)

    n_err  = len(report.errors)
    n_warn = len(report.warnings)
    n_info = len(report.infos)
    console.rule(style="dim")
    console.print(
        f"[red]{n_err} erreur(s)[/red]  "
        f"[yellow]{n_warn} avertissement(s)[/yellow]  "
        f"[green]{n_info} info(s)[/green]"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_translation(
    epub_path: Path,
    config: Config,
    *,
    output: Path | None = None,
    analysis_only: bool = False,
    resume: bool = False,
    skip_analysis: bool = False,
    prompts_dir: Path = Path("prompts"),
    retranslate: str | None = None,
) -> str | None:
    """
    Full pipeline: extract → analyse → translate → reconstruct.

    Returns the output path on success, None if aborted.
    """
    # ---- Clients (separate models for analysis vs translation) ----
    analysis_client = ClaudeClient(
        model=config.api.analysis_model,
        max_tokens=config.api.max_tokens_response,
        temperature=config.api.temperature,
    )
    client = ClaudeClient(
        model=config.api.model,
        max_tokens=config.api.max_tokens_response,
        temperature=config.api.temperature,
    )
    prompt_builder = PromptBuilder(prompts_dir)

    # ---- Phase 0: Extraction ----
    console.rule("[bold]Phase 0 : Extraction du ePub[/bold]")
    epub_content = extract_epub(epub_path)
    console.print(
        f"  Titre    : [cyan]{epub_content.metadata.get('title', 'Inconnu')}[/cyan]"
    )
    console.print(
        f"  Chapitres: [cyan]{sum(1 for i in epub_content.spine_items if i.is_chapter)}[/cyan]"
    )

    # ---- Cache ----
    config.output.cache_dir.mkdir(parents=True, exist_ok=True)
    config.output.analysis_dir.mkdir(parents=True, exist_ok=True)
    config.output.translated_dir.mkdir(parents=True, exist_ok=True)

    cache = CacheManager(
        epub_content.book_id,
        config.output.cache_dir,
        analysis_dir=config.output.analysis_dir,
    )

    # ---- Phase 1: Analysis ----
    console.rule("[bold]Phase 1 : Analyse du roman[/bold]")

    if skip_analysis and not cache.is_analysis_complete():
        console.print("[red]--skip-analysis demandé mais aucune analyse en cache.[/red]")
        sys.exit(1)

    analysis = await run_analysis(
        epub_content, analysis_client, prompt_builder, cache, config, console=console
    )

    display_analysis_summary(analysis, console)
    console.print(f"  [dim]Analyse sauvegardée : {cache.analysis_path}[/dim]")

    if analysis_only:
        console.print("[green]Analyse terminée (mode --analysis-only).[/green]")
        _print_usage(analysis_client)
        return None

    # ---- Human gate ----
    console.print(f"\n  Vous pouvez modifier [cyan]{cache.analysis_path}[/cyan] avant de continuer.")
    if not click.confirm("L'analyse est-elle satisfaisante ? (non = abandonner)"):
        console.print(
            "Relancez avec --skip-analysis pour utiliser le fichier modifié."
        )
        return None

    # Reload from disk so any manual edits made before confirming are picked up
    analysis = cache.load_analysis()

    # ---- Phase 2: Translation ----
    console.rule("[bold]Phase 2 : Traduction[/bold]")
    chapters = [item for item in epub_content.spine_items if item.is_chapter]

    # ---- Retranslate: resolve identifier and invalidate chapter ----
    retranslate_chapter_num: int | None = None
    if retranslate:
        table_path_existing = cache.cache_dir / "chapters.json"
        existing_table: list[dict] | None = None
        if table_path_existing.exists():
            try:
                existing_table = json.loads(table_path_existing.read_text(encoding="utf-8"))
            except Exception:
                pass
        retranslate_chapter_num = _resolve_retranslate(
            retranslate, epub_content.spine_items, existing_table
        )
        if retranslate_chapter_num is None:
            console.print(
                f"[red]--retranslate : chapitre introuvable pour « {retranslate} ».[/red]"
            )
            sys.exit(1)
        cache.invalidate_chapter(retranslate_chapter_num)
        console.print(
            f"  Chapitre [cyan]{retranslate_chapter_num + 1}[/cyan] invalidé — sera retraduit."
        )

    # ---- Resume (also forced when --retranslate is used, to keep other chapters) ----
    effective_resume = resume or retranslate_chapter_num is not None
    start_chapter = 0
    if effective_resume:
        last = cache.get_last_completed_chapter()
        start_chapter = last + 1
        if start_chapter > 0:
            if resume:
                console.print(f"Reprise depuis le fichier interne n°{start_chapter}.")
            # Restore already-translated chapters; skip any whose file was deleted
            missing: list[str] = []
            for chap in chapters[:start_chapter]:
                chapter_num = chap.chapter_number or 0
                if cache.is_chapter_complete(chapter_num):
                    chap.text_nodes = cache.load_chapter_result(chapter_num)
                elif chapter_num != retranslate_chapter_num:
                    # Don't warn for intentionally invalidated chapter
                    missing.append(Path(chap.filename).name)
            if missing:
                console.print(
                    f"  [yellow]Cache manquant pour : {', '.join(missing)} "
                    f"— ils seront retraduits.[/yellow]"
                )

    # ---- Correspondence table ----
    # Built after resume loading so cached chapters already have translated text_nodes.
    chapter_table = _build_chapter_table(epub_content.spine_items, cache)
    _display_chapter_table(chapter_table, console)
    table_path = cache.cache_dir / "chapters.json"
    _save_chapter_table(chapter_table, table_path)

    # Include chapters whose cache was deleted so they get retranslated
    chapters_to_translate = [
        chap for chap in chapters
        if not cache.is_chapter_complete(chap.chapter_number or 0)
    ]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Traduction", total=len(chapters_to_translate))

        for chapter in chapters_to_translate:
            chap_num = (chapter.chapter_number or 0) + 1
            title_en = extract_item_title(chapter)
            title_part = f" — {title_en[:38]}…" if title_en and len(title_en) > 38 else (f" — {title_en}" if title_en else "")
            cache_filename = f"chapter_{chapter.chapter_number or 0:04d}.json"
            label = (
                f"[cyan]↻[/cyan] Chap.{chap_num}{title_part}"
                f"  [dim]{Path(chapter.filename).name} │ {cache_filename}[/dim]"
            )
            progress.update(task, description=label)
            await translate_chapter(
                chapter=chapter,
                analysis=analysis,
                client=client,
                prompt_builder=prompt_builder,
                cache=cache,
                config=config,
                progress=progress,
                progress_task=task,
            )
            # Update table with FR title now available
            title_fr = extract_item_title(chapter, translated=True)
            for row in chapter_table:
                if row["chapter_number"] == chapter.chapter_number:
                    row["title_fr"] = title_fr
                    row["cached"] = True
                    break
            _save_chapter_table(chapter_table, table_path)
            progress.advance(task)

    # ---- Phase 3: Reconstruction ----
    console.rule("[bold]Phase 3 : Reconstruction du ePub[/bold]")

    if output is None:
        stem = epub_path.stem
        output = config.output.translated_dir / f"{stem}_fr.epub"

    result_path = reconstruct_epub(epub_content, output)

    badge_path = Path(__file__).parent.parent / "badge-IA.png"
    if apply_cover_badge(epub_path.parent, result_path, badge_path):
        console.print("[green]Badge IA appliqué sur la couverture.[/green]")

    console.print(f"\n[bold green]Traduction terminée : {result_path}[/bold green]")

    _print_usage(analysis_client, client)
    return str(result_path)


def _resolve_retranslate(
    identifier: str,
    spine_items: list[SpineItem],
    chapter_table: list[dict] | None = None,
) -> int | None:
    """Resolve a retranslate identifier to a 0-based chapter_number.

    Accepts (in order):
    - 1-based chapter number  e.g. "3"
    - Cache filename          e.g. "chapter_0002.json"
    - HTML filename           e.g. "chapter03.xhtml"
    - Title substring         e.g. "The Awakening"  (case-insensitive, FR or EN)
    """
    ident = identifier.strip()
    ident_lower = ident.lower()

    # 1. Pure integer → 1-based display number
    if ident.isdigit():
        target = int(ident) - 1
        for item in spine_items:
            if item.is_chapter and item.chapter_number == target:
                return target
        return None

    # 2. Cache filename
    if ident_lower.endswith(".json"):
        name = Path(ident_lower).name
        for item in spine_items:
            if item.is_chapter and item.chapter_number is not None:
                if f"chapter_{item.chapter_number:04d}.json" == name:
                    return item.chapter_number
        return None

    # 3. HTML filename
    if any(ident_lower.endswith(ext) for ext in (".xhtml", ".html", ".htm")):
        for item in spine_items:
            if item.is_chapter and Path(item.filename).name.lower() == ident_lower:
                return item.chapter_number
        return None

    # 4. Title substring — check chapter_table first (has FR titles)
    if chapter_table:
        for row in chapter_table:
            if row["chapter_number"] is None:
                continue
            for field in ("title_fr", "title_en"):
                t = row.get(field) or ""
                if t and ident_lower in t.lower():
                    return row["chapter_number"]

    # 5. Title substring — fall back to spine items (EN only)
    for item in spine_items:
        if not item.is_chapter:
            continue
        title = extract_item_title(item)
        if title and ident_lower in title.lower():
            return item.chapter_number

    return None


def _build_chapter_table(spine_items: list[SpineItem], cache: CacheManager) -> list[dict]:
    """Build the chapter correspondence table from spine items and cache state."""
    rows = []
    for i, item in enumerate(spine_items):
        title_en = extract_item_title(item, translated=False)
        title_fr = extract_item_title(item, translated=True)

        cache_file: str | None = None
        is_cached = False
        if item.is_chapter and item.chapter_number is not None:
            cache_file = f"chapter_{item.chapter_number:04d}.json"
            is_cached = cache.is_chapter_complete(item.chapter_number)

        if item.is_chapter:
            label = f"Chapitre {(item.chapter_number or 0) + 1}"
        else:
            label = classify_nonchapter_item(item.filename)

        rows.append({
            "spine_index": i,
            "chapter_number": item.chapter_number,
            "label": label,
            "title_en": title_en,
            "title_fr": title_fr,
            "html_file": Path(item.filename).name,
            "cache_file": cache_file,
            "cached": is_cached,
        })
    return rows


def _display_chapter_table(rows: list[dict], console: Console) -> None:
    """Display the chapter correspondence table using Rich."""
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("N°", no_wrap=True, min_width=10)
    table.add_column("Titre", no_wrap=False, max_width=42)
    table.add_column("Fichier HTML", style="dim", no_wrap=True, max_width=30)
    table.add_column("Cache", style="dim", no_wrap=True, max_width=22)

    for row in rows:
        title = row["title_fr"] or row["title_en"] or "[dim]—[/dim]"
        if len(title) > 40:
            title = title[:39] + "…"
        cache_cell = row["cache_file"] or "—"
        if row["cached"]:
            cache_cell += " [green]✓[/green]"
        table.add_row(row["label"], title, row["html_file"], cache_cell)

    console.print(table)


def _save_chapter_table(rows: list[dict], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _print_usage(*clients: ClaudeClient) -> None:
    total_in = total_out = total_cost = 0.0
    for c in clients:
        s = c.get_usage_summary()
        total_in   += s["input_tokens"]
        total_out  += s["output_tokens"]
        total_cost += s["estimated_cost_usd"]
        cache_info = ""
        if s["cache_read_tokens"] or s["cache_creation_tokens"]:
            cache_info = (
                f" | cache: {s['cache_creation_tokens']:,} write / "
                f"{s['cache_read_tokens']:,} read"
            )
        console.print(
            f"  [dim]{c.model}: {s['input_tokens']:,} in / "
            f"{s['output_tokens']:,} out{cache_info} — ${s['estimated_cost_usd']:.4f}[/dim]"
        )
    if len(clients) > 1:
        console.print(
            f"  [dim]Total : {int(total_in):,} in / {int(total_out):,} out — "
            f"[bold]${total_cost:.4f}[/bold][/dim]"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    cli()
