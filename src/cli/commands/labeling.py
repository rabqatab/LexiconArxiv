"""Abstract sentence labeling commands for LexiconArxiv CLI."""

import asyncio
import logging

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("label-abstracts")
    @click.option("--dry-run", is_flag=True, help="Preview without saving")
    @click.option("--limit", type=int, help="Maximum papers to process")
    @click.option("--batch-size", default=500, help="Papers per batch (default: 500)")
    @click.option("--force", is_flag=True, help="Re-label papers that already have abstract_structure")
    @click.option(
        "--llm-backend",
        type=click.Choice(["gemini", "ollama"]),
        default="gemini",
        help="LLM backend (default: gemini)",
    )
    @click.option(
        "--gemini-model",
        default="gemini-3-flash-preview",
        help="Gemini model name (default: gemini-3-flash-preview)",
    )
    @click.option(
        "--ollama-model",
        default="llama3.1:8b",
        help="Ollama model name (default: llama3.1:8b)",
    )
    @click.option(
        "--ollama-timeout",
        type=float,
        default=180.0,
        help="Ollama request timeout in seconds (default: 180)",
    )
    def label_abstracts(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        force: bool,
        llm_backend: str,
        gemini_model: str,
        ollama_model: str,
        ollama_timeout: float,
    ) -> None:
        """Classify abstract sentences into rhetorical roles.

        Labels each sentence in paper abstracts into 7 roles:
        task, domain, background, approach, method, result, contribution.

        Examples:

          # Dry run with Gemini (default)
          uv run python -m src.cli.core_collect label-abstracts --dry-run --limit 5

          # Dry run with Ollama
          uv run python -m src.cli.core_collect label-abstracts --llm-backend ollama --dry-run --limit 5

          # Label all unlabeled papers
          uv run python -m src.cli.core_collect label-abstracts --limit 100

          # Re-label all papers
          uv run python -m src.cli.core_collect label-abstracts --force --limit 50
        """
        asyncio.run(
            _label_abstracts_async(
                dry_run=dry_run,
                limit=limit,
                batch_size=batch_size,
                force=force,
                llm_backend=llm_backend,
                gemini_model=gemini_model,
                ollama_model=ollama_model,
                ollama_timeout=ollama_timeout,
            )
        )


async def _label_abstracts_async(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    force: bool,
    llm_backend: str,
    gemini_model: str,
    ollama_model: str,
    ollama_timeout: float,
) -> None:
    """Async abstract labeling pipeline."""
    from src.core.labeling import AbstractLabeler

    storage = QdrantStorage()
    labeler = AbstractLabeler(
        llm_backend=llm_backend,
        gemini_model=gemini_model,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
    )

    click.echo(f"Abstract labeling mode: LLM ({llm_backend})")

    if dry_run:
        click.echo("DRY RUN - changes will not be saved\n")

    try:
        processed, labeled, samples = await _run_labeling_loop(
            storage=storage,
            labeler=labeler,
            batch_size=batch_size,
            limit=limit,
            force=force,
            dry_run=dry_run,
        )

        _display_results(processed, labeled, samples, dry_run)
    finally:
        await labeler.close()


async def _run_labeling_loop(
    storage: QdrantStorage,
    labeler,
    batch_size: int,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> tuple[int, int, list[tuple[str, str, dict]]]:
    """Async labeling loop."""
    total_eligible = storage.count_papers_for_abstract_labeling(skip_existing=not force)
    if limit:
        total_eligible = min(total_eligible, limit)
    click.echo(f"Papers to process: {total_eligible:,}\n")

    processed = 0
    labeled = 0
    offset = None
    samples: list[tuple[str, str, dict]] = []

    while True:
        papers, next_offset = storage.get_papers_for_abstract_labeling(
            limit=batch_size,
            offset=offset,
            skip_existing=not force,
        )

        if not papers:
            break

        updates: list[tuple[str, dict, str]] = []

        # Filter papers with abstracts and apply limit
        eligible = []
        for point_id, payload in papers:
            title = payload.get("title", "")
            abstract = payload.get("abstract", "")
            if not abstract:
                processed += 1
                continue
            if limit and processed + len(eligible) >= limit:
                break
            eligible.append((point_id, title, abstract))

        # Process batch concurrently
        async def _label_one(point_id, title, abstract):
            return point_id, title, *await labeler.label_abstract(title, abstract)

        results = await asyncio.gather(
            *[_label_one(pid, t, a) for pid, t, a in eligible]
        )

        for point_id, title, structure, source in results:
            if structure:
                labeled += 1
                updates.append((point_id, structure, source))

                if dry_run and len(samples) < 10:
                    samples.append((title[:80], source, structure))

            processed += 1

        if not dry_run and updates:
            storage.batch_update_abstract_structure(updates)

        offset = next_offset

        pct = processed / total_eligible * 100 if total_eligible else 0
        click.echo(f"  Processed {processed:,}/{total_eligible:,} ({pct:.1f}%)")

        if limit and processed >= limit:
            break

        if offset is None:
            break

    return processed, labeled, samples


ROLES = ("task", "domain", "background", "approach", "method", "result", "contribution")


def _display_results(
    processed: int,
    labeled: int,
    samples: list[tuple[str, str, dict]],
    dry_run: bool,
) -> None:
    """Display labeling results summary."""
    click.echo(f"\n{'=' * 60}")
    click.echo("ABSTRACT LABELING COMPLETE")
    click.echo(f"{'=' * 60}\n")

    click.echo(f"Papers processed:  {processed:,}")
    click.echo(f"Papers labeled:    {labeled:,}")

    if dry_run and samples:
        click.echo(f"\n=== Sample Labels ===\n")
        for title, source, structure in samples:
            click.echo(f"Title:  {title}...")
            click.echo(f"Source: {source}")
            for role in ROLES:
                sentences = structure.get(role, [])
                click.echo(f"  {role:>14}: {sentences}")
            click.echo()

    if dry_run:
        click.echo("\nDRY RUN - no changes were saved. Run without --dry-run to save.")
