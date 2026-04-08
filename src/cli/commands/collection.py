"""Collection commands for LexiconArxiv CLI."""

import asyncio
import datetime
import logging
import sys

import click

from src.core.checkpoint import CheckpointManager
from src.core.config import (
    VENUES,
    get_venue_by_name,
    get_tier_venues,
    get_discovered_venues,
    get_undiscovered_venues,
)
from src.core.storage import QdrantStorage
from src.core.crawler import (
    CoreCorpusCollector,
    discover_source_id,
    discover_all_missing_sources,
    ACLAnthologyCollector,
    get_acl_venues,
    DBLPCollector,
    get_dblp_venues,
    OpenReviewCollector,
    get_openreview_venues,
    AAOJSCollector,
    get_aaai_venues,
)

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command()
    @click.option("--venue", "-V", help="Venue name to collect (e.g., neurips, acl)")
    @click.option("--tier", "-t", type=int, help="Collect all venues from tier (0 or 1)")
    @click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
    @click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
    @click.option("--all", "collect_all", is_flag=True, help="Collect from all discovered venues")
    @click.option("--count-only", is_flag=True, help="Only count papers, don't collect")
    def collect(
        venue: str | None,
        tier: int | None,
        since_year: int,
        to_year: int | None,
        collect_all: bool,
        count_only: bool,
    ) -> None:
        """Collect papers from OpenAlex venues.

        Examples:

          # Collect from NeurIPS
          python -m src.cli.core_collect collect --venue neurips

          # Collect all Tier 0 venues
          python -m src.cli.core_collect collect --tier 0

          # Collect from 2022 onwards
          python -m src.cli.core_collect collect --venue acl --since-year 2022

          # Collect all venues
          python -m src.cli.core_collect collect --all

          # Count papers before collecting (dry run)
          python -m src.cli.core_collect collect --all --count-only
        """
        if not any([venue, tier is not None, collect_all]):
            click.echo("Error: Specify --venue, --tier, or --all")
            sys.exit(1)

        async def run_count() -> dict[str, int]:
            async with CoreCorpusCollector() as collector:
                if collect_all or tier is not None:
                    return await collector.count_all(since_year, to_year)
                elif venue:
                    venue_config = get_venue_by_name(venue)
                    if not venue_config:
                        click.echo(f"Error: Unknown venue '{venue}'")
                        sys.exit(1)
                    count = await collector.count_venue(venue_config, since_year, to_year)
                    return {venue_config.name: count, "_total": count}
            return {}

        async def run_collection() -> int:
            storage = QdrantStorage()
            storage.ensure_collection()

            async with CoreCorpusCollector(storage=storage) as collector:
                if collect_all:
                    return await collector.collect_all(since_year, to_year)
                elif tier is not None:
                    return await collector.collect_tier(tier, since_year, to_year)
                elif venue:
                    venue_config = get_venue_by_name(venue)
                    if not venue_config:
                        click.echo(f"Error: Unknown venue '{venue}'")
                        click.echo(f"Available venues: {', '.join(v.name for v in VENUES)}")
                        sys.exit(1)

                    if not venue_config.is_discovered:
                        click.echo(f"Error: Venue '{venue}' has no Source ID. Run 'discover-sources' first.")
                        sys.exit(1)

                    total = 0
                    async for batch in collector.collect_venue(venue_config, since_year, to_year):
                        total += len(batch)
                        click.echo(f"Collected {total} papers from {venue_config.name}")
                    return total

            return 0

        if count_only:
            click.echo(f"\n=== Paper Count (OpenAlex, {since_year}-{to_year or 'present'}) ===\n")
            counts = asyncio.run(run_count())

            click.echo(f"\n{'Venue':<15} {'Count':>12}")
            click.echo("-" * 30)
            for name, count in sorted(counts.items()):
                if name != "_total":
                    click.echo(f"{name:<15} {count:>12,}")
            click.echo("-" * 30)
            click.echo(f"{'TOTAL':<15} {counts.get('_total', 0):>12,}")

            # Estimate time
            total = counts.get("_total", 0)
            est_minutes = (total / 200) * 0.6 / 60  # 200 per request, ~0.6s per request
            click.echo(f"\nEstimated collection time: {est_minutes:.1f} - {est_minutes * 2:.1f} minutes")
        else:
            total = asyncio.run(run_collection())
            click.echo(f"\nCollection complete: {total} papers")

    @cli.command()
    def status() -> None:
        """Show collection status and statistics."""
        # Load checkpoint
        checkpoint_manager = CheckpointManager()
        checkpoint = checkpoint_manager.load()

        click.echo("\n=== Collection Status ===\n")
        click.echo(f"Started: {checkpoint.started_at}")
        click.echo(f"Last updated: {checkpoint.last_updated or 'Never'}")
        click.echo(f"Since year: {checkpoint.since_year}")
        click.echo(f"Total papers: {checkpoint.total_papers}")
        click.echo(f"API calls: {checkpoint.total_api_calls}")

        click.echo("\n=== Venue Progress ===\n")

        # Show venue status
        for venue in VENUES:
            progress = checkpoint.get_venue_progress(venue.name)
            if progress:
                status_icon = "\u2713" if progress.is_complete else "\u2192"
                error_msg = f" (Error: {progress.error})" if progress.error else ""
                click.echo(
                    f"  {status_icon} {venue.name:12} Tier {venue.tier}  "
                    f"{progress.papers_collected:>6} papers{error_msg}"
                )
            else:
                discovered = "\u2713" if venue.is_discovered else "?"
                click.echo(f"  - {venue.name:12} Tier {venue.tier}  Not started ({discovered} Source ID)")

        # Try to get Qdrant stats
        try:
            storage = QdrantStorage()
            total_in_db = storage.count_papers()
            click.echo(f"\n=== Qdrant Storage ===\n")
            click.echo(f"Total papers in database: {total_in_db}")

            venue_stats = storage.get_venue_stats()
            if venue_stats:
                click.echo("\nPapers by venue:")
                for venue_name, count in sorted(venue_stats.items(), key=lambda x: -x[1]):
                    click.echo(f"  {venue_name:40} {count:>6}")
        except Exception as e:
            click.echo(f"\nNote: Could not connect to Qdrant: {e}")

    @cli.command("discover-sources")
    @click.option("--venue", "-V", help="Specific venue to discover")
    @click.option("--all", "discover_all", is_flag=True, help="Discover all missing Source IDs")
    def discover_sources(venue: str | None, discover_all: bool) -> None:
        """Discover OpenAlex Source IDs for venues.

        Examples:

          # Discover Source ID for ICLR
          python -m src.cli.core_collect discover-sources --venue iclr

          # Discover all missing Source IDs
          python -m src.cli.core_collect discover-sources --all
        """
        if not venue and not discover_all:
            click.echo("Error: Specify --venue or --all")
            sys.exit(1)

        async def run_discovery() -> None:
            if discover_all:
                undiscovered = get_undiscovered_venues()
                if not undiscovered:
                    click.echo("All venues have Source IDs!")
                    return

                click.echo(f"Discovering {len(undiscovered)} venues...\n")
                results = await discover_all_missing_sources()

                for venue_name, result in results.items():
                    click.echo(f"\n=== {venue_name} ===")
                    click.echo(f"Query: {result['query']}")

                    for match in result["matches"][:5]:
                        click.echo(f"\n  Source ID: {match['source_id']}")
                        click.echo(f"  Name: {match['display_name']}")
                        click.echo(f"  Type: {match['type']}")
                        click.echo(f"  Works: {match['works_count']:,}")

            elif venue:
                venue_config = get_venue_by_name(venue)
                if venue_config:
                    query = venue_config.full_name
                else:
                    query = venue

                click.echo(f"Searching for: {query}\n")
                result = await discover_source_id(query)

                for match in result["matches"]:
                    click.echo(f"\nSource ID: {match['source_id']}")
                    click.echo(f"Name: {match['display_name']}")
                    click.echo(f"Type: {match['type']}")
                    click.echo(f"Works: {match['works_count']:,}")
                    click.echo(f"Citations: {match['cited_by_count']:,}")

        asyncio.run(run_discovery())

    @cli.command("list-venues")
    @click.option("--tier", "-t", type=int, help="Filter by tier")
    @click.option("--discovered", is_flag=True, help="Show only discovered venues")
    @click.option("--missing", is_flag=True, help="Show only venues needing discovery")
    def list_venues(tier: int | None, discovered: bool, missing: bool) -> None:
        """List configured venues."""
        venues = VENUES

        if tier is not None:
            venues = get_tier_venues(tier)
        if discovered:
            venues = get_discovered_venues()
        if missing:
            venues = get_undiscovered_venues()

        click.echo("\n=== Configured Venues ===\n")
        click.echo(f"{'Name':12} {'Tier':6} {'Source ID':15} {'Full Name'}")
        click.echo("-" * 80)

        for venue in venues:
            source_id = venue.source_id or "TBD"
            click.echo(f"{venue.name:12} {venue.tier:6} {source_id:15} {venue.full_name}")

        click.echo(f"\nTotal: {len(venues)} venues")
        discovered_count = len([v for v in venues if v.is_discovered])
        click.echo(f"Discovered: {discovered_count}, Missing: {len(venues) - discovered_count}")

    @cli.command("clear-checkpoint")
    @click.confirmation_option(prompt="Are you sure you want to clear the checkpoint?")
    def clear_checkpoint() -> None:
        """Clear the collection checkpoint (reset progress)."""
        checkpoint_manager = CheckpointManager()
        checkpoint_manager.clear()
        click.echo("Checkpoint cleared.")

    @cli.command("init-storage")
    def init_storage() -> None:
        """Initialize Qdrant storage collection."""
        try:
            storage = QdrantStorage()
            created = storage.ensure_collection()
            if created:
                click.echo("Created Qdrant collection 'core_papers'")
            else:
                click.echo("Collection 'core_papers' already exists")

            count = storage.count_papers()
            click.echo(f"Current paper count: {count}")
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            click.echo("Make sure Qdrant is running at the configured URL")
            sys.exit(1)

    @cli.command("collect-incremental")
    @click.option("--days", "-d", default=1, help="Days to look back (default: 1)")
    @click.option("--source", "-s", type=click.Choice(["all", "openalex", "acl", "dblp", "openreview", "aaai"]),
                  default="all", help="Source to collect from")
    def collect_incremental(days: int, source: str) -> None:
        """Incremental collection for periodic updates.

        Fetches papers from the last N days. Supports daily, weekly, monthly,
        or quarterly update schedules. Automatically spans multiple years if needed.

        Examples:

          # Daily cron job (papers updated in last 24 hours)
          python -m src.cli.core_collect collect-incremental

          # Weekly catch-up
          python -m src.cli.core_collect collect-incremental --days 7

          # Monthly update
          python -m src.cli.core_collect collect-incremental --days 30

          # Quarterly update (3 months)
          python -m src.cli.core_collect collect-incremental --days 90

          # Only OpenAlex
          python -m src.cli.core_collect collect-incremental --source openalex

        Crontab examples:

          # Daily at 2 AM
          0 2 * * * cd /path/to/project && python -m src.cli.core_collect collect-incremental

          # Weekly on Sundays
          0 2 * * 0 cd /path/to/project && python -m src.cli.core_collect collect-incremental --days 7

          # Quarterly (1st of Jan, Apr, Jul, Oct)
          0 2 1 1,4,7,10 * cd /path/to/project && python -m src.cli.core_collect collect-incremental --days 90
        """
        since_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        since_year = int(since_date[:4])  # Extract year from date range start
        current_year = datetime.datetime.now().year

        click.echo(f"\n=== Incremental Collection (since {since_date}) ===\n")
        if since_year < current_year:
            click.echo(f"Note: Collecting from {since_year} to {current_year} (spans multiple years)\n")

        async def run_incremental() -> dict[str, int]:
            storage = QdrantStorage()
            storage.ensure_collection()

            results = {}

            # OpenAlex
            if source in ["all", "openalex"]:
                click.echo("Collecting from OpenAlex...")
                async with CoreCorpusCollector(storage=storage) as collector:
                    count = await collector.collect_incremental(days_back=days)
                    results["openalex"] = count
                    click.echo(f"  OpenAlex: {count} new papers")

            # ACL Anthology - collect from since_year to current_year
            if source in ["all", "acl"]:
                click.echo(f"Collecting from ACL Anthology ({since_year}-{current_year})...")
                async with ACLAnthologyCollector(storage=storage) as collector:
                    count = 0
                    for venue in get_acl_venues():
                        async for batch in collector.collect_venue(venue, since_year=since_year, to_year=current_year, force=True):
                            count += len(batch)
                    results["acl"] = count
                    click.echo(f"  ACL Anthology: {count} new papers")

            # DBLP - collect from since_year to current_year
            if source in ["all", "dblp"]:
                click.echo(f"Collecting from DBLP ({since_year}-{current_year})...")
                async with DBLPCollector(storage=storage) as collector:
                    count = 0
                    for venue in get_dblp_venues():
                        async for batch in collector.collect_venue(venue, since_year=since_year, to_year=current_year, force=True):
                            count += len(batch)
                    results["dblp"] = count
                    click.echo(f"  DBLP: {count} new papers")

            # OpenReview - collect from since_year to current_year
            if source in ["all", "openreview"]:
                click.echo(f"Collecting from OpenReview ({since_year}-{current_year})...")
                async with OpenReviewCollector(storage=storage) as collector:
                    count = 0
                    for venue in get_openreview_venues():
                        async for batch in collector.collect_venue(venue, since_year=since_year, to_year=current_year, force=True):
                            count += len(batch)
                    results["openreview"] = count
                    click.echo(f"  OpenReview: {count} new papers")

            # AAAI - collect from since_year to current_year
            if source in ["all", "aaai"]:
                click.echo(f"Collecting from AAAI OJS ({since_year}-{current_year})...")
                async with AAOJSCollector(storage=storage) as collector:
                    count = 0
                    for venue in get_aaai_venues():
                        async for batch in collector.collect_venue(venue, since_year=since_year, to_year=current_year, force=True):
                            count += len(batch)
                    results["aaai"] = count
                    click.echo(f"  AAAI OJS: {count} new papers")

            return results

        results = asyncio.run(run_incremental())

        total = sum(results.values())
        click.echo(f"\n=== Summary ===")
        click.echo(f"Total new papers: {total}")

        # Log timestamp for cron
        click.echo(f"Completed at: {datetime.datetime.now().isoformat()}")

    @cli.command("dedup-cleanup")
    @click.option("--dry-run", is_flag=True, help="Report duplicates without deleting")
    @click.option("--collection", "-c", default=None, help="Qdrant collection name")
    def dedup_cleanup(dry_run: bool, collection: str | None) -> None:
        """Find and remove duplicate papers in the corpus.

        Scrolls all non-stub papers, groups by DOI (or OpenAlex ID if no
        DOI), and for each duplicate group keeps the paper with the richest
        data (has abstract, keywords, vectors) and deletes the rest.

        Examples:

          # Preview duplicates
          python -m src.cli.core_collect dedup-cleanup --dry-run

          # Remove duplicates
          python -m src.cli.core_collect dedup-cleanup
        """
        from collections import defaultdict
        from qdrant_client.http import models

        storage = QdrantStorage(collection_name=collection) if collection else QdrantStorage()

        click.echo("\n=== Duplicate Cleanup ===\n")
        click.echo("Scanning all non-stub papers...")

        # ---- 1. Scroll all non-stub papers and group by identifier ----
        doi_groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        oa_groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)

        offset = None
        scanned = 0
        while True:
            results, next_offset = storage.client.scroll(
                collection_name=storage.collection_name,
                scroll_filter=models.Filter(
                    must_not=[
                        models.FieldCondition(
                            key="is_stub",
                            match=models.MatchValue(value=True),
                        ),
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=True,
            )
            if not results:
                break
            for point in results:
                pid = str(point.id)
                payload = point.payload or {}
                doi = payload.get("doi")
                oa_id = payload.get("openalex_id")
                if doi:
                    doi_groups[doi.lower()].append((pid, payload))
                elif oa_id:
                    oa_groups[oa_id].append((pid, payload))
                scanned += 1
            if next_offset is None:
                break
            offset = next_offset

        click.echo(f"Scanned {scanned:,} non-stub papers")

        # ---- 2. Identify duplicates ----
        def _richness_score(payload: dict) -> int:
            """Higher score = more data-rich paper (preferred to keep)."""
            score = 0
            abstract = payload.get("abstract") or ""
            if abstract and abstract.strip():
                score += 4
            if payload.get("abstract_structure"):
                score += 3
            if payload.get("keywords"):
                score += 2
            if payload.get("code_repos"):
                score += 1
            # Prefer longer abstracts as a tiebreak
            score += min(len(abstract) // 200, 3)
            return score

        ids_to_delete: list[str] = []
        dup_group_count = 0

        for label, groups in [("DOI", doi_groups), ("OpenAlex ID", oa_groups)]:
            for key, members in groups.items():
                if len(members) <= 1:
                    continue
                dup_group_count += 1
                # Sort by richness descending; keep first (richest)
                members.sort(key=lambda m: _richness_score(m[1]), reverse=True)
                keeper_id, keeper_payload = members[0]
                duplicates = members[1:]

                if dry_run:
                    click.echo(
                        f"  [{label}] {key}: {len(members)} copies — "
                        f"keeping {keeper_id} "
                        f"(score={_richness_score(keeper_payload)}), "
                        f"would delete {len(duplicates)}"
                    )

                for dup_id, _ in duplicates:
                    ids_to_delete.append(dup_id)

        click.echo(f"\nDuplicate groups: {dup_group_count:,}")
        click.echo(f"Papers to {'delete' if not dry_run else 'remove (dry-run)'}: {len(ids_to_delete):,}")

        # ---- 3. Delete duplicates ----
        if ids_to_delete and not dry_run:
            # Delete in batches
            batch_size = 500
            deleted = 0
            for i in range(0, len(ids_to_delete), batch_size):
                batch = ids_to_delete[i : i + batch_size]
                storage.client.delete(
                    collection_name=storage.collection_name,
                    points_selector=models.PointIdsList(points=batch),
                )
                deleted += len(batch)
                click.echo(f"  Deleted {deleted:,} / {len(ids_to_delete):,}")

            click.echo(f"\nRemoved {deleted:,} duplicate papers")
        elif not ids_to_delete:
            click.echo("\nNo duplicates found!")
        else:
            click.echo("\nDry run complete. Re-run without --dry-run to delete.")
