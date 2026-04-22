"""Data quality commands for LexiconArxiv CLI."""

import json
import logging
import sys

import click

from src.core.deduplication import Deduplicator
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("deduplicate")
    @click.option("--dry-run", is_flag=True, help="Show duplicates without deleting")
    @click.option("--collection", "-c", type=str, help="Qdrant collection name")
    def deduplicate(dry_run: bool, collection: str | None) -> None:
        """Remove duplicate papers from Qdrant collection.

        Identifies duplicates by source_id and keeps the first occurrence.
        This is useful for cleaning up after collecting from sources separately
        (not using collect-all-sources which has cross-source deduplication).

        Examples:

          # Preview duplicates
          python -m src.cli.core_collect deduplicate --dry-run

          # Remove duplicates
          python -m src.cli.core_collect deduplicate

          # Specify collection name
          python -m src.cli.core_collect deduplicate --collection my_collection
        """
        from collections import defaultdict
        from qdrant_client import models

        click.echo("\n=== Post-Collection Deduplication ===\n")

        try:
            storage = QdrantStorage(collection_name=collection) if collection else QdrantStorage()
            click.echo(f"Collection: {storage.collection_name}")
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        # Track source_ids to find duplicates
        source_id_to_points: dict[str, list[str]] = defaultdict(list)
        title_to_points: dict[str, list[tuple[str, str]]] = defaultdict(list)  # (point_id, source_id)

        click.echo("Scanning collection for duplicates...")

        # Scroll through all papers
        offset = None
        total_scanned = 0
        while True:
            results, offset = storage.client.scroll(
                collection_name=storage.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["source_id", "title", "year"],
            )

            for point in results:
                source_id = point.payload.get("source_id")
                title = point.payload.get("title", "")
                year = point.payload.get("year")

                if source_id:
                    source_id_to_points[source_id].append(point.id)

                # Also track by normalized title+year
                if title:
                    title_key = Deduplicator.make_title_year_key(title, year)
                    title_to_points[title_key].append((point.id, source_id or "unknown"))

            total_scanned += len(results)
            if total_scanned % 10000 == 0:
                click.echo(f"  Scanned {total_scanned} papers...")

            if offset is None:
                break

        click.echo(f"  Scanned {total_scanned} total papers")

        # Find duplicates by source_id
        source_id_duplicates = {
            sid: points for sid, points in source_id_to_points.items()
            if len(points) > 1
        }

        # Find duplicates by title+year (excluding already counted by source_id)
        title_duplicates = {}
        for title_key, point_list in title_to_points.items():
            if len(point_list) > 1:
                # Check if these are different source_ids (cross-source duplicates)
                unique_sources = set(src for _, src in point_list)
                if len(unique_sources) > 1:
                    title_duplicates[title_key] = point_list

        # Calculate stats
        source_id_dup_count = sum(len(pts) - 1 for pts in source_id_duplicates.values())
        title_dup_count = sum(len(pts) - 1 for pts in title_duplicates.values())

        click.echo(f"\n=== Duplicate Analysis ===\n")
        click.echo(f"  Unique source_ids: {len(source_id_to_points)}")
        click.echo(f"  Source_id duplicates: {len(source_id_duplicates)} groups ({source_id_dup_count} extra points)")
        click.echo(f"  Title+year cross-source duplicates: {len(title_duplicates)} groups ({title_dup_count} extra points)")

        if source_id_duplicates:
            click.echo(f"\n  Sample source_id duplicates:")
            for sid, points in list(source_id_duplicates.items())[:5]:
                click.echo(f"    - {sid}: {len(points)} copies")

        if title_duplicates:
            click.echo(f"\n  Sample title+year duplicates (cross-source):")
            for title_key, point_list in list(title_duplicates.items())[:5]:
                sources = [src for _, src in point_list]
                click.echo(f"    - '{title_key[:50]}...': {len(point_list)} copies from {sources}")

        if not source_id_duplicates and not title_duplicates:
            click.echo("\n  No duplicates found!")
            return

        if dry_run:
            click.echo(f"\n  Dry run - no changes made.")
            click.echo(f"  Run without --dry-run to remove duplicates.")
            return

        # Delete duplicates (keep first, delete rest)
        click.echo(f"\n  Removing duplicates...")

        points_to_delete = []

        # Collect source_id duplicate points (keep first)
        for sid, points in source_id_duplicates.items():
            points_to_delete.extend(points[1:])  # Keep first, delete rest

        # Collect title+year cross-source duplicate points (keep first)
        for title_key, point_list in title_duplicates.items():
            point_ids = [pid for pid, _ in point_list]
            points_to_delete.extend(point_ids[1:])  # Keep first, delete rest

        # Remove duplicates from points_to_delete (in case same point is in both lists)
        points_to_delete = list(set(points_to_delete))

        # Batch delete
        deleted = 0
        for i in range(0, len(points_to_delete), 100):
            batch = points_to_delete[i:i+100]
            storage.client.delete(
                collection_name=storage.collection_name,
                points_selector=models.PointIdsList(points=batch)
            )
            deleted += len(batch)
            if deleted % 500 == 0:
                click.echo(f"    Deleted {deleted} points...")

        click.echo(f"\n=== Deduplication Complete ===\n")
        click.echo(f"  Deleted: {deleted} duplicate points")
        click.echo(f"  Remaining: {total_scanned - deleted} papers")

    @cli.command("data-quality")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    @click.option("--by-venue", is_flag=True, help="Show breakdown by venue")
    def data_quality(output_json: bool, by_venue: bool) -> None:
        """Show data quality statistics and coverage gaps.

        Displays comprehensive statistics about the corpus including:
        - Paper counts by source
        - DOI, abstract, and citation coverage
        - Enrichment potential

        Examples:

          # Show data quality report
          python -m src.cli.core_collect data-quality

          # Output as JSON
          python -m src.cli.core_collect data-quality --json

          # Show breakdown by venue
          python -m src.cli.core_collect data-quality --by-venue
        """
        try:
            storage = QdrantStorage()
            click.echo("Analyzing data quality (this may take a moment)...")
            stats = storage.get_data_quality_stats()
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        if output_json:
            # Remove venue stats if not requested (can be large)
            if not by_venue:
                stats.pop("by_venue", None)
            click.echo(json.dumps(stats, indent=2))
            return

        # Pretty print report
        click.echo(f"\n{'=' * 60}")
        click.echo("DATA QUALITY REPORT")
        click.echo(f"{'=' * 60}\n")

        total = stats["total"]
        click.echo(f"Total papers: {total:,}\n")

        # Summary
        summary = stats["summary"]
        click.echo("=== Coverage Summary ===\n")
        click.echo(f"{'Metric':<25} {'Count':>10} {'Percent':>10}")
        click.echo("-" * 47)
        click.echo(f"{'Papers with DOI':<25} {summary['has_doi']:>10,} {summary['has_doi']/total*100 if total else 0:>9.1f}%")
        click.echo(f"{'Papers with abstract':<25} {summary['has_abstract']:>10,} {summary['has_abstract']/total*100 if total else 0:>9.1f}%")
        click.echo(f"{'Papers with refs':<25} {summary['has_refs']:>10,} {summary['has_refs']/total*100 if total else 0:>9.1f}%")

        # By source
        click.echo(f"\n=== By Source ===\n")
        click.echo(f"{'Source':<15} {'Papers':>8} {'Has DOI':>10} {'Has Abs':>10} {'Has Refs':>10}")
        click.echo("-" * 55)

        for source, source_stats in sorted(stats["by_source"].items(), key=lambda x: -x[1]["count"]):
            count = source_stats["count"]
            doi_pct = source_stats["has_doi"] / count * 100 if count else 0
            abs_pct = source_stats["has_abstract"] / count * 100 if count else 0
            refs_pct = source_stats["has_refs"] / count * 100 if count else 0
            click.echo(f"{source:<15} {count:>8,} {doi_pct:>9.1f}% {abs_pct:>9.1f}% {refs_pct:>9.1f}%")

        # Enrichment potential
        potential = stats["enrichment_potential"]
        click.echo(f"\n=== Enrichment Potential ===\n")
        click.echo(f"Citation enrichment: {potential['citations']:,} papers (have DOI, missing refs)")
        click.echo(f"Abstract enrichment: {potential['abstracts']:,} papers (have DOI, missing abstract)")

        # By venue (optional)
        if by_venue and stats.get("by_venue"):
            click.echo(f"\n=== By Venue ===\n")
            click.echo(f"{'Venue':<30} {'Papers':>8} {'Has DOI':>10} {'Has Abs':>10} {'Has Refs':>10}")
            click.echo("-" * 70)

            for venue, venue_stats in sorted(stats["by_venue"].items(), key=lambda x: -x[1]["count"]):
                count = venue_stats["count"]
                doi_pct = venue_stats["has_doi"] / count * 100 if count else 0
                abs_pct = venue_stats["has_abstract"] / count * 100 if count else 0
                refs_pct = venue_stats["has_refs"] / count * 100 if count else 0
                venue_display = venue[:28] + ".." if len(venue) > 30 else venue
                click.echo(f"{venue_display:<30} {count:>8,} {doi_pct:>9.1f}% {abs_pct:>9.1f}% {refs_pct:>9.1f}%")

    @cli.command("reset-title-enriched")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="Show what would be reset without making changes")
    @click.option("--checkpoint", type=str,
                  default="data/core/checkpoints/title_citations_enrichment.json",
                  help="Path to title enrichment checkpoint")
    def reset_title_enriched(dry_run: bool, checkpoint: str) -> None:
        """Reset all title-enriched papers so they can be re-matched with stricter logic.

        Finds all papers that received DOIs from title-based enrichment
        (Stage 3.3), clears their DOI, referenced_works, and abstract,
        and removes them from the title and abstracts checkpoints.
        The not_found papers stay in the checkpoint so 3.3 only
        re-processes the enriched ones (~42K credits instead of ~500K).

        After running this, re-run the pipeline from Stage 3.3 onward.

        Examples:

          # Preview what will be reset
          uv run python -m src.cli.core_collect reset-title-enriched --dry-run

          # Reset and prepare for re-run
          uv run python -m src.cli.core_collect reset-title-enriched
        """
        from pathlib import Path

        checkpoint_path = Path(checkpoint)
        if not checkpoint_path.exists():
            click.echo(f"Checkpoint not found: {checkpoint_path}")
            sys.exit(1)

        with open(checkpoint_path) as f:
            ckpt = json.load(f)

        all_ids = list(ckpt.get("processed_point_ids", []))
        enriched_count = ckpt.get("enriched", 0)
        not_found_count = ckpt.get("not_found", 0)
        click.echo(f"Title checkpoint: {ckpt.get('processed', 0)} processed, "
                    f"{enriched_count} enriched, {not_found_count} not_found")

        # Fetch papers that have DOIs (these got DOIs from title enrichment)
        try:
            storage = QdrantStorage()
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        click.echo("Finding title-enriched papers with DOIs...")
        enriched_ids = []
        for i in range(0, len(all_ids), 100):
            batch = all_ids[i:i + 100]
            try:
                points = storage.client.retrieve(
                    collection_name=storage.collection_name,
                    ids=batch,
                    with_payload=["doi"],
                )
                for p in points:
                    if p.payload.get("doi"):
                        enriched_ids.append(p.id)
            except Exception as e:
                click.echo(f"  Warning: batch fetch error: {e}")

        click.echo(f"Papers to reset: {len(enriched_ids)}")
        click.echo(f"Papers to keep in checkpoint (not_found): {len(all_ids) - len(enriched_ids)}")
        click.echo(f"Estimated re-run cost: {len(enriched_ids) * 10:,} credits (~{len(enriched_ids) * 10 / 100_000:.1f} keys)")

        if dry_run:
            click.echo("\nDry run — no changes made.")
            return

        if not enriched_ids:
            click.echo("\nNo enriched papers found. Nothing to reset.")
            return

        enriched_set = set(enriched_ids)

        # 1. Clear DOI, referenced_works, abstract in Qdrant
        # Note: set_payload with None deletes the field (Qdrant behavior).
        # Use delete_payload for doi/abstract, and set_payload for referenced_works.
        click.echo(f"\nClearing DOI, refs, and abstract for {len(enriched_ids)} papers...")
        cleared = 0
        for i in range(0, len(enriched_ids), 100):
            batch = enriched_ids[i:i + 100]
            try:
                storage.client.delete_payload(
                    collection_name=storage.collection_name,
                    keys=["doi", "abstract"],
                    points=batch,
                )
                storage.client.set_payload(
                    collection_name=storage.collection_name,
                    payload={"referenced_works": []},
                    points=batch,
                )
                cleared += len(batch)
            except Exception as e:
                click.echo(f"  Error clearing batch: {e}")
        click.echo(f"  Cleared {cleared} papers")

        # 2. Remove enriched IDs from title checkpoint (keep not_found)
        click.echo("Updating title checkpoint (removing enriched, keeping not_found)...")
        remaining_ids = [pid for pid in all_ids if pid not in enriched_set]
        ckpt["processed_point_ids"] = remaining_ids
        ckpt["processed"] = len(remaining_ids)
        ckpt["enriched"] = 0
        with open(checkpoint_path, "w") as f:
            json.dump(ckpt, f, indent=2)
        click.echo(f"  Title checkpoint: {len(remaining_ids)} IDs kept (was {len(all_ids)})")

        # 3. Remove enriched IDs from abstracts checkpoint
        abstracts_ckpt_path = Path("data/core/checkpoints/abstracts_enrichment.json")
        if abstracts_ckpt_path.exists():
            try:
                with open(abstracts_ckpt_path) as f:
                    abs_ckpt = json.load(f)
                old_abs_ids = set(abs_ckpt.get("processed_point_ids", []))
                removed = old_abs_ids & enriched_set
                if removed:
                    abs_ckpt["processed_point_ids"] = list(old_abs_ids - enriched_set)
                    abs_ckpt["processed"] = len(abs_ckpt["processed_point_ids"])
                    with open(abstracts_ckpt_path, "w") as f:
                        json.dump(abs_ckpt, f, indent=2)
                    click.echo(f"  Abstracts checkpoint: removed {len(removed)} IDs")
                else:
                    click.echo("  Abstracts checkpoint: no overlap found")
            except Exception as e:
                click.echo(f"  Warning: could not update abstracts checkpoint: {e}")
        else:
            click.echo("  Abstracts checkpoint: not found (OK)")

        click.echo(f"\n{'=' * 50}")
        click.echo("DONE")
        click.echo(f"{'=' * 50}")
        click.echo(f"  Reset: {cleared} papers (DOI, refs, abstract cleared)")
        click.echo(f"  Title checkpoint: {len(remaining_ids)} not_found kept")
        click.echo(f"\nNext: re-run pipeline from 3.3 onward:")
        click.echo(f"  scripts/run_full_pipeline.sh \\")
        click.echo(f"    --since-year 2017 \\")
        click.echo(f"    --skip-collection --skip-dedup \\")
        click.echo(f"    --skip-openalex --skip-crossref \\")
        click.echo(f"    --log logs/pipeline_resume.log")
