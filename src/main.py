"""CLI entry point for epub-translator."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from src.analyzer import display_analysis_summary, run_analysis
from src.cache_manager import CacheManager
from src.claude_client import ClaudeClient
from src.epub_handler import extract_epub, reconstruct_epub
from src.models import Config
from src.prompt_builder import PromptBuilder
from src.translator import translate_chapter
from src.utils import load_config

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """Traducteur de romans ePub EN→FR avec analyse professionnelle."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@cli.command()
@click.argument("epub_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output ePub path.")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="config.yaml", show_default=True, help="Config YAML file.")
@click.option("--analysis-only", is_flag=True, default=False, help="Run analysis only, do not translate.")
@click.option("--resume", is_flag=True, default=False, help="Resume an interrupted translation.")
@click.option("--skip-analysis", is_flag=True, default=False, help="Skip analysis, use cached result.")
@click.option("--prompts-dir", type=click.Path(path_type=Path), default="prompts", show_default=True, help="Directory containing prompt templates.")
def translate(
    epub_path: Path,
    output: Path | None,
    config_path: Path,
    analysis_only: bool,
    resume: bool,
    skip_analysis: bool,
    prompts_dir: Path,
) -> None:
    """Traduit un roman ePub de l'anglais au français."""
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
        )
    )


@cli.command("clear-cache")
@click.argument("epub_path", type=click.Path(exists=True, path_type=Path))
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="config.yaml", show_default=True, help="Config YAML file.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
def clear_cache(epub_path: Path, config_path: Path, yes: bool) -> None:
    """Supprime le cache (analyse + chapitres) pour un ePub donné."""
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
) -> str | None:
    """
    Full pipeline: extract → analyse → translate → reconstruct.

    Returns the output path on success, None if aborted.
    """
    # ---- Shared objects ----
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
        epub_content, client, prompt_builder, cache, config, console=console
    )

    display_analysis_summary(analysis, console)
    console.print(f"  [dim]Analyse sauvegardée : {cache.analysis_path}[/dim]")

    if analysis_only:
        console.print("[green]Analyse terminée (mode --analysis-only).[/green]")
        _print_usage(client)
        return None

    # ---- Human gate ----
    if not click.confirm("\nL'analyse est-elle satisfaisante ? (non = abandonner)"):
        console.print(
            "Vous pouvez modifier le fichier d'analyse et relancer avec --skip-analysis."
        )
        return None

    # ---- Phase 2: Translation ----
    console.rule("[bold]Phase 2 : Traduction[/bold]")
    chapters = [item for item in epub_content.spine_items if item.is_chapter]

    start_chapter = 0
    if resume:
        last = cache.get_last_completed_chapter()
        start_chapter = last + 1
        if start_chapter > 0:
            console.print(f"Reprise depuis le chapitre {start_chapter}.")
            # Restore already-translated chapters from cache
            for chap in chapters[:start_chapter]:
                chap.text_nodes = cache.load_chapter_result(chap.chapter_number or 0)

    chapters_to_translate = chapters[start_chapter:]

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Traduction", total=len(chapters_to_translate))

        for i, chapter in enumerate(chapters_to_translate):
            label = f"[cyan]Chapitre {(chapter.chapter_number or 0) + 1}[/cyan] ({chapter.filename})"
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
            progress.advance(task)

    # ---- Phase 3: Reconstruction ----
    console.rule("[bold]Phase 3 : Reconstruction du ePub[/bold]")

    if output is None:
        stem = epub_path.stem
        output = config.output.translated_dir / f"{stem}_fr.epub"

    result_path = reconstruct_epub(epub_content, output)
    console.print(f"\n[bold green]Traduction terminée : {result_path}[/bold green]")

    _print_usage(client)
    return str(result_path)


def _print_usage(client: ClaudeClient) -> None:
    summary = client.get_usage_summary()
    console.print(
        f"\n[dim]Tokens utilisés: {summary['input_tokens']:,} input / "
        f"{summary['output_tokens']:,} output — "
        f"Coût estimé: ${summary['estimated_cost_usd']:.4f}[/dim]"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    cli()
