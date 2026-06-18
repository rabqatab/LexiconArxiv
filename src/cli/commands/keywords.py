"""Keyword extraction commands for LexiconArxiv CLI."""

import asyncio
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
    @click.option(
        "--embedding-model",
        default="all-MiniLM-L6-v2",
        help="Sentence-transformers model for KeyBERT (default: all-MiniLM-L6-v2)",
    )
    @click.option("--llm", "use_llm", is_flag=True, help="Enable LLM keyword extraction (Ollama)")
    @click.option("--judge", "use_judge", is_flag=True, help="Enable LLM judge validation (Ollama)")
    @click.option(
        "--ollama-model",
        default="qwen3.5:27b",
        help="Ollama model name (default: qwen3.5:27b)",
    )
    @click.option(
        "--ollama-timeout",
        type=float,
        default=180.0,
        help="Ollama request timeout in seconds (default: 180)",
    )
    def extract_keywords(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        no_keybert: bool,
        force: bool,
        embedding_model: str,
        use_llm: bool,
        use_judge: bool,
        ollama_model: str,
        ollama_timeout: float,
    ) -> None:
        """Extract keywords from paper titles and abstracts.

        LLM-first extraction pipeline:
        1. LLM extraction via Ollama (primary, always attempted)
        2. Fallback: regex + KeyBERT (only when LLM is unavailable or fails)
        3. LLM judge validation (optional, also via Ollama)

        Examples:

          # Extract keywords for all papers (default: regex + KeyBERT)
          uv run python -m src.cli.core_collect extract-keywords

          # Full Ollama LLM pipeline with judge
          uv run python -m src.cli.core_collect extract-keywords --llm --judge

          # Use a different Ollama model
          uv run python -m src.cli.core_collect extract-keywords --llm --ollama-model llama3.1:8b

          # Better embeddings
          uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

          # Preview full pipeline
          uv run python -m src.cli.core_collect extract-keywords --llm --judge --dry-run --limit 10
        """
        needs_async = use_llm or use_judge

        if needs_async:
            asyncio.run(
                _extract_keywords_async(
                    dry_run=dry_run,
                    limit=limit,
                    batch_size=batch_size,
                    no_keybert=no_keybert,
                    force=force,
                    embedding_model=embedding_model,
                    use_llm=use_llm,
                    use_judge=use_judge,
                    ollama_model=ollama_model,
                    ollama_timeout=ollama_timeout,
                )
            )
        else:
            _extract_keywords_sync(
                dry_run=dry_run,
                limit=limit,
                batch_size=batch_size,
                no_keybert=no_keybert,
                force=force,
                embedding_model=embedding_model,
            )

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
          uv run python -m src.cli.core_collect keyword-stats

          # Output as JSON
          uv run python -m src.cli.core_collect keyword-stats --json
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
          uv run python -m src.cli.core_collect clear-keyword-checkpoint

          # Clear without prompting
          uv run python -m src.cli.core_collect clear-keyword-checkpoint --confirm
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
          uv run python -m src.cli.core_collect clear-keywords --confirm
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


def _extract_keywords_sync(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    no_keybert: bool,
    force: bool,
    embedding_model: str,
) -> None:
    """Synchronous keyword extraction (regex + KeyBERT only)."""
    from src.core.keyword import KeywordExtractor

    storage = QdrantStorage()
    extractor = KeywordExtractor(
        use_keybert=not no_keybert,
        embedding_model=embedding_model,
    )

    mode = "regex only" if no_keybert else "regex + KeyBERT"
    click.echo(f"Keyword extraction mode: {mode}")
    if embedding_model != "all-MiniLM-L6-v2":
        click.echo(f"Embedding model: {embedding_model}")

    if dry_run:
        click.echo("DRY RUN - changes will not be saved\n")

    processed, papers_with_keywords, total_keywords, samples = _run_extraction_loop(
        storage=storage,
        extractor=extractor,
        batch_size=batch_size,
        limit=limit,
        force=force,
        dry_run=dry_run,
    )

    _display_results(processed, papers_with_keywords, total_keywords, samples, dry_run)


async def _extract_keywords_async(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    no_keybert: bool,
    force: bool,
    embedding_model: str,
    use_llm: bool,
    use_judge: bool,
    ollama_model: str,
    ollama_timeout: float,
) -> None:
    """Async keyword extraction (with LLM and/or judge via Ollama)."""
    from src.core.keyword import KeywordExtractor

    storage = QdrantStorage()
    extractor = KeywordExtractor(
        use_keybert=not no_keybert,
        embedding_model=embedding_model,
        use_llm=use_llm,
        use_judge=use_judge,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
    )

    if use_llm:
        parts = ["LLM (ollama)"]
        if not no_keybert:
            parts.append("fallback: regex + KeyBERT")
        else:
            parts.append("fallback: regex")
    else:
        parts = ["regex"]
        if not no_keybert:
            parts.append("KeyBERT")
    if use_judge:
        parts.append("judge (ollama)")
    click.echo(f"Keyword extraction mode: {' + '.join(parts)}")

    if dry_run:
        click.echo("DRY RUN - changes will not be saved\n")

    try:
        processed, papers_with_keywords, total_keywords, samples = (
            await _run_extraction_loop_async(
                storage=storage,
                extractor=extractor,
                batch_size=batch_size,
                limit=limit,
                force=force,
                dry_run=dry_run,
            )
        )

        _display_results(
            processed, papers_with_keywords, total_keywords, samples, dry_run
        )
    finally:
        await extractor.close()


def _run_extraction_loop(
    storage: QdrantStorage,
    extractor,
    batch_size: int,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[tuple[str, str, list[str]]]]:
    """Synchronous extraction loop (regex + KeyBERT only)."""
    try:
        total_eligible = storage.count_papers_for_keyword_extraction(skip_existing=not force)
        if limit:
            total_eligible = min(total_eligible, limit)
        click.echo(f"Papers to process: {total_eligible:,}\n")
    except Exception:
        total_eligible = None
        click.echo("Papers to process: (count unavailable)\n")

    processed = 0
    papers_with_keywords = 0
    total_keywords = 0
    offset = None
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

            if dry_run and len(samples) < 10 and keywords:
                samples.append((title[:80], source, keywords))

            processed += 1
            if limit and processed >= limit:
                break

        if not dry_run and updates:
            storage.batch_update_keywords_with_source(updates)

        offset = next_offset

        if total_eligible:
            pct = processed / total_eligible * 100
            click.echo(f"  Processed {processed:,}/{total_eligible:,} ({pct:.1f}%)")
        else:
            click.echo(f"  Processed {processed:,} papers...")

        if limit and processed >= limit:
            break

        if offset is None:
            break

    return processed, papers_with_keywords, total_keywords, samples


async def _run_extraction_loop_async(
    storage: QdrantStorage,
    extractor,
    batch_size: int,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> tuple[int, int, int, list[tuple[str, str, list[str], dict | None]]]:
    """Async extraction loop (with LLM and/or judge)."""
    try:
        total_eligible = storage.count_papers_for_keyword_extraction(skip_existing=not force)
        if limit:
            total_eligible = min(total_eligible, limit)
        click.echo(f"Papers to process: {total_eligible:,}\n")
    except Exception:
        total_eligible = None
        click.echo("Papers to process: (count unavailable)\n")

    processed = 0
    papers_with_keywords = 0
    total_keywords = 0
    offset = None
    samples: list[tuple[str, str, list[str], dict | None]] = []

    while True:
        papers, next_offset = storage.get_papers_for_keyword_extraction(
            limit=batch_size,
            offset=offset,
            skip_existing=not force,
        )

        if not papers:
            break

        updates: list[tuple[str, list[str], str, dict | None]] = []

        # Collect eligible papers and apply limit
        eligible = []
        for point_id, payload in papers:
            title = payload.get("title", "")
            abstract = payload.get("abstract")
            if limit and processed + len(eligible) >= limit:
                break
            eligible.append((point_id, title, abstract))

        # Process batch concurrently
        async def _extract_one(point_id, title, abstract):
            kw, src, structured = await extractor.extract_pipeline_with_source(title, abstract)
            return point_id, title, kw, src, structured

        results = await asyncio.gather(
            *[_extract_one(pid, t, a) for pid, t, a in eligible]
        )

        for point_id, title, keywords, source, structured in results:
            if keywords:
                papers_with_keywords += 1
                total_keywords += len(keywords)

            updates.append((point_id, keywords, source, structured))

            if dry_run and len(samples) < 10 and keywords:
                samples.append((title[:80], source, keywords, structured))

            processed += 1

        if not dry_run and updates:
            storage.batch_update_keywords_with_source(updates)

        offset = next_offset

        if total_eligible:
            pct = processed / total_eligible * 100
            click.echo(f"  Processed {processed:,}/{total_eligible:,} ({pct:.1f}%)")
        else:
            click.echo(f"  Processed {processed:,} papers...")

        if limit and processed >= limit:
            break

        if offset is None:
            break

    return processed, papers_with_keywords, total_keywords, samples


def _display_results(
    processed: int,
    papers_with_keywords: int,
    total_keywords: int,
    samples: list,
    dry_run: bool,
) -> None:
    """Display extraction results summary."""
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
        for sample in samples:
            # Support both 3-tuple (sync) and 4-tuple (async with structured)
            if len(sample) == 4:
                title, source, keywords, structured = sample
            else:
                title, source, keywords = sample
                structured = None

            click.echo(f"Title:    {title}...")
            click.echo(f"Source:   {source}")
            click.echo(f"Keywords: {keywords}")
            if structured:
                for category in ("task", "method", "model", "domain", "dataset",
                                "contribution_type", "modality"):
                    values = structured.get(category, [])
                    click.echo(f"  {category:>8}: {values}")
            click.echo()

    if dry_run:
        click.echo("\nDRY RUN - no changes were saved. Run without --dry-run to save.")
