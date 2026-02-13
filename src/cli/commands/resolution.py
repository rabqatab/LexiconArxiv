"""Reference resolution commands for LexiconArxiv CLI."""

import asyncio
import json
import logging
import sys

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("resolve-refs")
    @click.option("--dry-run", is_flag=True, help="Count papers without updating")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--step", type=click.Choice(["all", "normalize", "arxiv", "internal"]),
                  default="all", help="Run specific step only")
    @click.option("--fuzzy-matching", is_flag=True, help="Use fuzzy title matching (slower)")
    @click.option("--external-search", is_flag=True, help="Search external APIs for unresolved titles")
    @click.option("--create-stubs/--no-create-stubs", default=True, help="Create stub papers for unresolved references (default: enabled)")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--parallel", "-p", type=int, default=5, help="Concurrent requests")
    def resolve_refs(
        dry_run: bool,
        limit: int | None,
        step: str,
        fuzzy_matching: bool,
        external_search: bool,
        create_stubs: bool,
        batch_size: int,
        parallel: int,
    ) -> None:
        """Resolve raw reference identifiers to internal paper IDs.

        This builds a citation graph by mapping referenced_works identifiers
        (DOI, arXiv, TITLE) to internal Qdrant point IDs in resolved_references.

        Pipeline steps:
          1. normalize - Fix malformed identifiers (arXiv:arXiv:..., DOI case)
          2. arxiv    - Convert arXiv refs to DOIs via OpenAlex lookup
          3. internal - Map identifiers to internal point IDs

        Examples:

          # Run full pipeline (dry run)
          python -m src.cli.core_collect resolve-refs --dry-run

          # Run full pipeline
          python -m src.cli.core_collect resolve-refs

          # Run specific step
          python -m src.cli.core_collect resolve-refs --step normalize
          python -m src.cli.core_collect resolve-refs --step arxiv
          python -m src.cli.core_collect resolve-refs --step internal

          # With fuzzy title matching (slower but better coverage)
          python -m src.cli.core_collect resolve-refs --step internal --fuzzy-matching

          # Search external APIs for unresolved titles
          python -m src.cli.core_collect resolve-refs --step internal --external-search

          # Skip stub paper creation (stubs are created by default)
          python -m src.cli.core_collect resolve-refs --no-create-stubs

          # Limit papers processed
          python -m src.cli.core_collect resolve-refs --limit 1000
        """
        from src.core.resolution.resolver import ReferenceResolver

        async def run_resolution():
            storage = QdrantStorage()
            async with ReferenceResolver(
                storage=storage,
                batch_size=batch_size,
                max_concurrent=parallel,
            ) as resolver:
                if step == "all":
                    results = await resolver.run_full_pipeline(
                        dry_run=dry_run,
                        limit=limit,
                        fuzzy_matching=fuzzy_matching,
                        external_search=external_search,
                        create_stubs=create_stubs,
                    )

                    click.echo(f"\n{'=' * 50}")
                    click.echo("REFERENCE RESOLUTION SUMMARY")
                    click.echo(f"{'=' * 50}\n")

                    for step_name, progress in results.items():
                        click.echo(f"Step: {step_name}")
                        click.echo(f"  Processed: {progress.processed}")
                        click.echo(f"  Updated:   {progress.updated}")
                        if step_name == "normalize":
                            click.echo(f"  Refs normalized: {progress.refs_normalized}")
                        elif step_name == "arxiv":
                            click.echo(f"  arXiv resolved:  {progress.arxiv_resolved}")
                        elif step_name == "internal":
                            click.echo(f"  DOIs resolved:     {progress.dois_resolved}")
                            click.echo(f"  OpenAlex resolved: {progress.openalex_resolved}")
                            click.echo(f"  Titles resolved:   {progress.titles_resolved}")
                            if progress.external_added > 0:
                                click.echo(f"  External added:    {progress.external_added}")
                            if progress.stubs_created > 0:
                                click.echo(f"  Stubs created:     {progress.stubs_created}")
                        click.echo()

                elif step == "normalize":
                    progress = await resolver.normalize_references(
                        dry_run=dry_run, limit=limit
                    )
                    click.echo(f"\nNormalization Results:")
                    click.echo(f"  Processed:       {progress.processed}")
                    click.echo(f"  Updated:         {progress.updated}")
                    click.echo(f"  Refs normalized: {progress.refs_normalized}")

                elif step == "arxiv":
                    progress = await resolver.resolve_arxiv_to_doi(
                        dry_run=dry_run, limit=limit
                    )
                    click.echo(f"\narXiv->DOI Resolution Results:")
                    click.echo(f"  Processed:      {progress.processed}")
                    click.echo(f"  Updated:        {progress.updated}")
                    click.echo(f"  arXiv resolved: {progress.arxiv_resolved}")

                elif step == "internal":
                    progress = await resolver.resolve_to_internal_ids(
                        dry_run=dry_run,
                        limit=limit,
                        fuzzy_matching=fuzzy_matching,
                        external_search=external_search,
                        create_stubs=create_stubs,
                    )
                    click.echo(f"\nInternal ID Resolution Results:")
                    click.echo(f"  Processed:         {progress.processed}")
                    click.echo(f"  Updated:           {progress.updated}")
                    click.echo(f"  DOIs resolved:     {progress.dois_resolved}")
                    click.echo(f"  OpenAlex resolved: {progress.openalex_resolved}")
                    click.echo(f"  Titles resolved:   {progress.titles_resolved}")
                    if progress.external_added > 0:
                        click.echo(f"  External added:    {progress.external_added}")
                    if progress.stubs_created > 0:
                        click.echo(f"  Stubs created:     {progress.stubs_created}")

                if dry_run:
                    click.echo("\n  (Dry run - no changes made)")

        asyncio.run(run_resolution())

    @cli.command("ref-stats")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    def ref_stats(output_json: bool) -> None:
        """Show reference resolution statistics.

        Displays statistics about referenced_works and resolved_references:
        - Total papers with references
        - Reference types (DOI, arXiv, TITLE, etc.)
        - Resolution coverage

        Examples:

          python -m src.cli.core_collect ref-stats
          python -m src.cli.core_collect ref-stats --json
        """
        try:
            storage = QdrantStorage()
            click.echo("Analyzing reference data (this may take a moment)...")
            stats = storage.get_reference_stats()
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        if output_json:
            click.echo(json.dumps(stats, indent=2))
            return

        click.echo(f"\n{'=' * 50}")
        click.echo("REFERENCE STATISTICS")
        click.echo(f"{'=' * 50}\n")

        total = stats["total_papers"]
        with_refs = stats["papers_with_refs"]
        with_resolved = stats["papers_with_resolved_refs"]
        total_refs = stats["total_references"]
        total_resolved = stats["total_resolved"]

        click.echo(f"Total papers:              {total:,}")
        click.echo(f"Papers with references:    {with_refs:,} ({with_refs/total*100:.1f}%)" if total else f"Papers with references:    {with_refs:,}")
        click.echo(f"Papers with resolved refs: {with_resolved:,} ({with_resolved/total*100:.1f}%)" if total else f"Papers with resolved refs: {with_resolved:,}")
        click.echo()
        click.echo(f"Total references:          {total_refs:,}")
        click.echo(f"Total resolved:            {total_resolved:,}")
        if total_refs > 0:
            click.echo(f"Resolution rate:           {total_resolved/total_refs*100:.1f}%")

        click.echo(f"\n=== Reference Types ===\n")
        ref_types = stats["ref_types"]
        for ref_type, count in sorted(ref_types.items(), key=lambda x: -x[1]):
            if count > 0:
                pct = count / total_refs * 100 if total_refs > 0 else 0
                click.echo(f"  {ref_type:10} {count:>10,} ({pct:5.1f}%)")

    @cli.command("clear-resolve-checkpoint")
    @click.option("--step", type=click.Choice(["normalize", "arxiv", "internal", "all"]),
                  default="all", help="Step checkpoint to clear")
    def clear_resolve_checkpoint(step: str) -> None:
        """Clear reference resolution checkpoint.

        Examples:

          # Clear all resolution checkpoints
          python -m src.cli.core_collect clear-resolve-checkpoint

          # Clear specific step checkpoint
          python -m src.cli.core_collect clear-resolve-checkpoint --step normalize
          python -m src.cli.core_collect clear-resolve-checkpoint --step arxiv
          python -m src.cli.core_collect clear-resolve-checkpoint --step internal
        """
        from src.core.resolution.resolver import ReferenceResolver

        resolver = ReferenceResolver()
        resolver.clear_checkpoint(step)

        if step == "all":
            click.echo("All reference resolution checkpoints cleared.")
        else:
            click.echo(f"Reference resolution checkpoint cleared: {step}")

    @cli.command("stub-stats")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    @click.option("--top", "-n", type=int, default=20, help="Show top N most-cited stubs")
    def stub_stats(output_json: bool, top: int) -> None:
        """Show statistics about stub papers (external references).

        Stub papers are external papers that appear in references but aren't
        in the corpus. They're created during resolve-refs --create-stubs.

        Examples:

          python -m src.cli.core_collect stub-stats
          python -m src.cli.core_collect stub-stats --top 50
          python -m src.cli.core_collect stub-stats --json
        """
        try:
            storage = QdrantStorage()
            stats = storage.get_stub_stats()
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        if output_json:
            click.echo(json.dumps(stats, indent=2))
            return

        click.echo(f"\n{'=' * 50}")
        click.echo("STUB PAPER STATISTICS")
        click.echo(f"{'=' * 50}\n")

        click.echo(f"Total stub papers:       {stats['total_stubs']:,}")
        click.echo(f"Stubs with metadata:     {stats['stubs_with_metadata']:,}")
        click.echo(f"Total internal citations:{stats['total_internal_citations']:,}")
        if stats["total_stubs"] > 0:
            click.echo(f"Avg citations per stub:  {stats['avg_citations_per_stub']:.1f}")

        if stats["total_stubs"] > 0:
            click.echo(f"\n=== Stub Types ===\n")
            for id_type, count in sorted(stats["by_identifier_type"].items(), key=lambda x: -x[1]):
                pct = count / stats["total_stubs"] * 100
                click.echo(f"  {id_type:10} {count:>10,} ({pct:5.1f}%)")

            # Show most cited stubs
            click.echo(f"\n=== Most-Cited External Papers (Top {top}) ===\n")
            most_cited = storage.get_most_cited_stubs(limit=top)
            if most_cited:
                for i, (stub_id, payload) in enumerate(most_cited, 1):
                    identifier = payload.get("identifier", "unknown")
                    cited_count = payload.get("cited_by_count_internal", 0)
                    title = payload.get("title")
                    if title:
                        display = f"{title[:50]}..." if len(title) > 50 else title
                    else:
                        display = identifier
                    click.echo(f"  {i:3}. [{cited_count:4} citations] {display}")
            else:
                click.echo("  No stubs found with citations.")
