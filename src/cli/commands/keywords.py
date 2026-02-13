"""Keyword extraction commands for LexiconArxiv CLI."""

import json
import logging
from pathlib import Path

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("extract-keywords")
    @click.option("--dry-run", is_flag=True, help="Preview without saving")
    @click.option("--limit", type=int, help="Maximum papers to process")
    @click.option("--batch-size", default=100, help="Papers per batch (default: 100)")
    @click.option("--no-keybert", is_flag=True, help="Use only regex patterns (faster)")
    @click.option("--force", is_flag=True, help="Re-extract for papers that already have keywords")
    def extract_keywords(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        no_keybert: bool,
        force: bool,
    ) -> None:
        """Extract keywords from paper titles and abstracts.

        Uses a two-phase extraction pipeline:
        1. Regex patterns for acronyms (BERT, HyDE, RAG, etc.)
        2. KeyBERT for semantic keywords (optional)

        Examples:

          # Extract keywords for all papers
          python -m src.cli.core_collect extract-keywords

          # Preview without saving
          python -m src.cli.core_collect extract-keywords --dry-run --limit 10

          # Use only regex (faster, no KeyBERT model loading)
          python -m src.cli.core_collect extract-keywords --no-keybert

          # Re-extract keywords for all papers
          python -m src.cli.core_collect extract-keywords --force
        """
        from src.core.keyword import KeywordExtractor

        storage = QdrantStorage()
        extractor = KeywordExtractor(use_keybert=not no_keybert)

        mode = "regex only" if no_keybert else "regex + KeyBERT"
        click.echo(f"Keyword extraction mode: {mode}")

        if dry_run:
            click.echo("DRY RUN - changes will not be saved\n")

        # Track stats
        processed = 0
        papers_with_keywords = 0
        total_keywords = 0
        offset = None

        # Sample for dry run display
        samples: list[tuple[str, str, list[str]]] = []

        while True:
            papers, next_offset = storage.get_papers_for_keyword_extraction(
                limit=batch_size,
                offset=offset,
                skip_existing=not force,
            )

            if not papers:
                break

            updates: list[tuple[str, list[str], str]] = []

            for point_id, payload in papers:
                title = payload.get("title", "")
                abstract = payload.get("abstract")

                keywords = extractor.extract(title, abstract)
                source = extractor.get_extraction_source(title, abstract)

                if keywords:
                    papers_with_keywords += 1
                    total_keywords += len(keywords)

                updates.append((point_id, keywords, source))

                # Collect samples for dry run
                if dry_run and len(samples) < 5 and keywords:
                    samples.append((title[:60], source, keywords[:5]))

                processed += 1
                if limit and processed >= limit:
                    break

            # Save if not dry run
            if not dry_run and updates:
                storage.batch_update_keywords_with_source(updates)

            offset = next_offset

            # Progress
            if processed % 500 == 0:
                click.echo(f"  Processed {processed} papers...")

            if limit and processed >= limit:
                break

            if offset is None:
                break

        # Display results
        click.echo(f"\n{'=' * 60}")
        click.echo("KEYWORD EXTRACTION COMPLETE")
        click.echo(f"{'=' * 60}\n")

        click.echo(f"Papers processed:       {processed:,}")
        click.echo(f"Papers with keywords:   {papers_with_keywords:,}")
        click.echo(f"Total keywords:         {total_keywords:,}")

        if papers_with_keywords > 0:
            avg = total_keywords / papers_with_keywords
            click.echo(f"Avg keywords per paper: {avg:.2f}")

        # Show samples in dry run
        if dry_run and samples:
            click.echo(f"\n=== Sample Extractions ===\n")
            for title, source, keywords in samples:
                click.echo(f"Title:    {title}...")
                click.echo(f"Source:   {source}")
                click.echo(f"Keywords: {keywords}")
                click.echo()

        if dry_run:
            click.echo("\nDRY RUN - no changes were saved. Run without --dry-run to save.")

    @cli.command("keyword-stats")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    def keyword_stats(output_json: bool) -> None:
        """Show keyword extraction statistics.

        Displays metrics about keyword extraction including:
        - Papers with/without keywords
        - Total and average keywords
        - Breakdown by extraction source

        Examples:

          # Show keyword stats
          python -m src.cli.core_collect keyword-stats

          # Output as JSON
          python -m src.cli.core_collect keyword-stats --json
        """
        storage = QdrantStorage()

        click.echo("Calculating keyword statistics...")
        stats = storage.get_keyword_stats()

        if output_json:
            click.echo(json.dumps(stats, indent=2))
            return

        # Pretty print
        click.echo(f"\n{'=' * 50}")
        click.echo("KEYWORD EXTRACTION STATISTICS")
        click.echo(f"{'=' * 50}\n")

        total = stats["total_papers"]
        with_kw = stats["papers_with_keywords"]
        without_kw = stats["papers_without_keywords"]

        click.echo(f"Total papers:           {total:,}")
        click.echo(f"Papers with keywords:   {with_kw:,} ({with_kw/total*100:.1f}%)" if total else "")
        click.echo(f"Papers without keywords:{without_kw:,} ({without_kw/total*100:.1f}%)" if total else "")
        click.echo()

        click.echo(f"Total keywords:         {stats['total_keywords']:,}")
        click.echo(f"Avg per paper:          {stats['avg_keywords_per_paper']:.2f}")
        click.echo()

        # By source
        click.echo("=== By Extraction Source ===\n")
        click.echo(f"{'Source':<15} {'Count':>10} {'Percent':>10}")
        click.echo("-" * 37)

        by_source = stats["by_source"]
        for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
            pct = count / total * 100 if total else 0
            click.echo(f"{source:<15} {count:>10,} {pct:>9.1f}%")

    @cli.command("clear-keyword-checkpoint")
    @click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
    def clear_keyword_checkpoint(confirm: bool) -> None:
        """Clear the keyword extraction checkpoint.

        This allows you to restart keyword extraction from the beginning.

        Examples:

          # Clear checkpoint with confirmation
          python -m src.cli.core_collect clear-keyword-checkpoint

          # Clear without prompting
          python -m src.cli.core_collect clear-keyword-checkpoint --confirm
        """
        checkpoint_file = Path("data/core/checkpoints/keyword_extraction.json")

        if not checkpoint_file.exists():
            click.echo("No keyword extraction checkpoint found.")
            return

        if not confirm:
            if not click.confirm("Clear keyword extraction checkpoint?"):
                click.echo("Cancelled.")
                return

        checkpoint_file.unlink()
        click.echo("Keyword extraction checkpoint cleared.")

    @cli.command("clear-keywords")
    @click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
    def clear_keywords(confirm: bool) -> None:
        """Clear all keywords from the corpus.

        WARNING: This removes all extracted keywords. You will need to
        re-run extract-keywords to regenerate them.

        Examples:

          # Clear all keywords
          python -m src.cli.core_collect clear-keywords --confirm
        """
        if not confirm:
            click.echo("WARNING: This will remove all keywords from all papers.")
            if not click.confirm("Are you sure you want to continue?"):
                click.echo("Cancelled.")
                return

        storage = QdrantStorage()
        click.echo("Clearing keywords from all papers...")

        cleared = storage.clear_all_keywords()
        click.echo(f"Cleared keywords from {cleared:,} papers.")
