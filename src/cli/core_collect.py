"""CLI for Core Corpus collection.

Provides commands for collecting papers from Tier 0/1 venues,
checking status, and discovering Source IDs.

Supports multiple sources: OpenAlex, ACL Anthology, and DBLP.
"""

import asyncio
import datetime
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import click

from src.core.checkpoint import CheckpointManager
from src.core.config import (
    VENUES,
    get_venue_by_name,
    get_tier_venues,
    get_discovered_venues,
    get_undiscovered_venues,
)
from src.core.deduplication import Deduplicator
from src.core.storage import QdrantStorage
from src.core.crawler import (
    CoreCorpusCollector,
    discover_source_id,
    discover_all_missing_sources,
    ACLAnthologyCollector,
    get_acl_venues,
    ACL_VENUES,
    DBLPCollector,
    get_dblp_venues,
    DBLP_VENUES,
    OpenReviewCollector,
    get_openreview_venues,
    OPENREVIEW_VENUES,
    ACMOpenCollector,
    get_acm_open_venues,
    ACM_OPEN_VENUES,
    AAOJSCollector,
    get_aaai_venues,
    AAAI_VENUES,
)

# Configure logging (console + file)
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "lexiconarxiv.log"

# Create formatters
log_format = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)


# File handler with immediate flush for real-time log saving
class FlushingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that flushes after every emit for real-time logging."""
    def emit(self, record):
        super().emit(record)
        self.flush()


# File handler (rotating, 10MB max, keep 5 backups)
file_handler = FlushingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_format)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Core Corpus collection CLI for LexiconArxiv."""
    if verbose:
        root_logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)


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
            status_icon = "✓" if progress.is_complete else "→"
            error_msg = f" (Error: {progress.error})" if progress.error else ""
            click.echo(
                f"  {status_icon} {venue.name:12} Tier {venue.tier}  "
                f"{progress.papers_collected:>6} papers{error_msg}"
            )
        else:
            discovered = "✓" if venue.is_discovered else "?"
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
@click.option("--source", "-s", type=click.Choice(["all", "openalex", "acl", "dblp", "openreview", "acm", "aaai"]),
              default="all", help="Source to collect from")
def collect_incremental(days: int, source: str) -> None:
    """Incremental collection for daily cron jobs.

    Fetches only papers updated in the last N days. Designed to be run
    daily via crontab to keep the corpus up-to-date.

    Examples:

      # Daily cron job (papers updated in last 24 hours)
      python -m src.cli.core_collect collect-incremental

      # Weekly catch-up
      python -m src.cli.core_collect collect-incremental --days 7

      # Only OpenAlex
      python -m src.cli.core_collect collect-incremental --source openalex

      # Only new sources
      python -m src.cli.core_collect collect-incremental --source openreview

    Crontab example (daily at 2 AM):
      0 2 * * * cd /path/to/project && python -m src.cli.core_collect collect-incremental >> /var/log/lexicon_cron.log 2>&1
    """
    since_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    click.echo(f"\n=== Incremental Collection (since {since_date}) ===\n")

    async def run_incremental() -> dict[str, int]:
        storage = QdrantStorage()
        storage.ensure_collection()

        results = {}
        current_year = datetime.datetime.now().year

        # OpenAlex
        if source in ["all", "openalex"]:
            click.echo("Collecting from OpenAlex...")
            async with CoreCorpusCollector(storage=storage) as collector:
                count = await collector.collect_incremental(days_back=days)
                results["openalex"] = count
                click.echo(f"  OpenAlex: {count} new papers")

        # ACL Anthology - check recent years only (no date-based API)
        if source in ["all", "acl"]:
            click.echo("Collecting from ACL Anthology...")
            async with ACLAnthologyCollector(storage=storage) as collector:
                count = 0
                for venue in get_acl_venues():
                    async for batch in collector.collect_venue(venue, since_year=current_year):
                        count += len(batch)
                results["acl"] = count
                click.echo(f"  ACL Anthology: {count} new papers")

        # DBLP - check recent years only
        if source in ["all", "dblp"]:
            click.echo("Collecting from DBLP...")
            async with DBLPCollector(storage=storage) as collector:
                count = 0
                for venue in get_dblp_venues():
                    async for batch in collector.collect_venue(venue, since_year=current_year):
                        count += len(batch)
                results["dblp"] = count
                click.echo(f"  DBLP: {count} new papers")

        # OpenReview - check recent years only
        if source in ["all", "openreview"]:
            click.echo("Collecting from OpenReview...")
            async with OpenReviewCollector(storage=storage) as collector:
                count = 0
                for venue in get_openreview_venues():
                    async for batch in collector.collect_venue(venue, since_year=current_year):
                        count += len(batch)
                results["openreview"] = count
                click.echo(f"  OpenReview: {count} new papers")

        # ACM - check recent years only
        if source in ["all", "acm"]:
            click.echo("Collecting from ACM Open...")
            async with ACMOpenCollector(storage=storage) as collector:
                count = 0
                for venue in get_acm_open_venues():
                    async for batch in collector.collect_venue(venue, since_year=current_year):
                        count += len(batch)
                results["acm"] = count
                click.echo(f"  ACM Open: {count} new papers")

        # AAAI - check recent years only
        if source in ["all", "aaai"]:
            click.echo("Collecting from AAAI OJS...")
            async with AAOJSCollector(storage=storage) as collector:
                count = 0
                for venue in get_aaai_venues():
                    async for batch in collector.collect_venue(venue, since_year=current_year):
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


# ============================================================================
# ACL Anthology Commands
# ============================================================================


@cli.command("collect-acl")
@click.option("--venue", "-V", help="ACL venue name (e.g., acl, emnlp, naacl)")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--all", "collect_all", is_flag=True, help="Collect from all ACL venues")
@click.option("--include-workshops", is_flag=True, help="Include workshop papers (with --all)")
@click.option("--workshops-only", is_flag=True, help="Collect only workshop papers")
def collect_acl(
    venue: str | None,
    since_year: int,
    to_year: int | None,
    collect_all: bool,
    include_workshops: bool,
    workshops_only: bool,
) -> None:
    """Collect papers from ACL Anthology.

    Examples:

      # Collect from ACL main conference
      python -m src.cli.core_collect collect-acl --venue acl

      # Collect from EMNLP from 2022 onwards
      python -m src.cli.core_collect collect-acl --venue emnlp --since-year 2022

      # Collect from all ACL venues (main venues only)
      python -m src.cli.core_collect collect-acl --all

      # Collect from all ACL venues including workshops
      python -m src.cli.core_collect collect-acl --all --include-workshops

      # Collect only workshop papers
      python -m src.cli.core_collect collect-acl --workshops-only
    """
    if not any([venue, collect_all, workshops_only]):
        click.echo("Error: Specify --venue, --all, or --workshops-only")
        click.echo(f"Available ACL venues: {', '.join(get_acl_venues())}")
        sys.exit(1)

    async def run_collection() -> int:
        storage = QdrantStorage()
        storage.ensure_collection()

        async with ACLAnthologyCollector(storage=storage) as collector:
            if workshops_only:
                # Collect only workshops
                total = 0
                async for batch in collector.collect_workshops(since_year, to_year):
                    total += len(batch)
                    click.echo(f"Collected {total} workshop papers")
                return total
            elif collect_all:
                return await collector.collect_all(since_year, to_year, include_workshops=include_workshops)
            elif venue:
                venue_lower = venue.lower()
                if venue_lower == "workshops":
                    # Special case for workshops
                    total = 0
                    async for batch in collector.collect_workshops(since_year, to_year):
                        total += len(batch)
                        click.echo(f"Collected {total} workshop papers")
                    return total
                elif venue_lower not in ACL_VENUES:
                    click.echo(f"Error: Unknown ACL venue '{venue}'")
                    click.echo(f"Available venues: {', '.join(get_acl_venues())}, workshops")
                    sys.exit(1)

                total = 0
                async for batch in collector.collect_venue(venue_lower, since_year, to_year):
                    total += len(batch)
                    click.echo(f"Collected {total} papers from ACL {venue}")
                return total

        return 0

    total = asyncio.run(run_collection())
    click.echo(f"\nACL collection complete: {total} papers")


@cli.command("list-acl-venues")
def list_acl_venues() -> None:
    """List available ACL Anthology venues."""
    click.echo("\n=== ACL Anthology Venues ===\n")
    click.echo(f"{'Name':12} {'Tier':6} {'Full Name'}")
    click.echo("-" * 70)

    for name, info in ACL_VENUES.items():
        click.echo(f"{name:12} {info['tier']:6} {info['full_name']}")

    # Show workshops as a special entry
    click.echo(f"{'workshops':12} {'2':6} {'ACL-Affiliated Workshops (collected dynamically)'}")

    click.echo(f"\nTotal: {len(ACL_VENUES)} main venues + workshops")
    click.echo("\nTo collect workshops, use:")
    click.echo("  python -m src.cli.core_collect collect-acl --all --include-workshops")
    click.echo("  python -m src.cli.core_collect collect-acl --workshops-only")


# ============================================================================
# DBLP Commands
# ============================================================================


@cli.command("collect-dblp")
@click.option("--venue", "-V", help="DBLP venue name (e.g., recsys, icail, jurix)")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--all", "collect_all", is_flag=True, help="Collect from all DBLP venues")
def collect_dblp(
    venue: str | None,
    since_year: int,
    to_year: int | None,
    collect_all: bool,
) -> None:
    """Collect papers from DBLP.

    Examples:

      # Collect from RecSys
      python -m src.cli.core_collect collect-dblp --venue recsys

      # Collect from ICAIL (legal AI)
      python -m src.cli.core_collect collect-dblp --venue icail --since-year 2020

      # Collect from all DBLP venues
      python -m src.cli.core_collect collect-dblp --all
    """
    if not any([venue, collect_all]):
        click.echo("Error: Specify --venue or --all")
        click.echo(f"Available DBLP venues: {', '.join(get_dblp_venues())}")
        sys.exit(1)

    async def run_collection() -> int:
        storage = QdrantStorage()
        storage.ensure_collection()

        async with DBLPCollector(storage=storage) as collector:
            if collect_all:
                return await collector.collect_all(since_year, to_year)
            elif venue:
                venue_lower = venue.lower()
                if venue_lower not in DBLP_VENUES:
                    click.echo(f"Error: Unknown DBLP venue '{venue}'")
                    click.echo(f"Available venues: {', '.join(get_dblp_venues())}")
                    sys.exit(1)

                total = 0
                async for batch in collector.collect_venue(venue_lower, since_year, to_year):
                    total += len(batch)
                    click.echo(f"Collected {total} papers from DBLP {venue}")
                return total

        return 0

    total = asyncio.run(run_collection())
    click.echo(f"\nDBLP collection complete: {total} papers")


@cli.command("list-dblp-venues")
def list_dblp_venues() -> None:
    """List available DBLP venues."""
    click.echo("\n=== DBLP Venues ===\n")
    click.echo(f"{'Name':12} {'Tier':6} {'Full Name'}")
    click.echo("-" * 70)

    for name, info in DBLP_VENUES.items():
        click.echo(f"{name:12} {info['tier']:6} {info['full_name']}")

    click.echo(f"\nTotal: {len(DBLP_VENUES)} venues")


# ============================================================================
# OpenReview Commands
# ============================================================================


@cli.command("collect-openreview")
@click.option("--venue", "-V", help="OpenReview venue name (e.g., iclr, neurips, icml)")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--all", "collect_all", is_flag=True, help="Collect from all OpenReview venues")
@click.option("--include-rejected", is_flag=True, help="Include rejected/withdrawn submissions (default: accepted only)")
def collect_openreview(
    venue: str | None,
    since_year: int,
    to_year: int | None,
    collect_all: bool,
    include_rejected: bool,
) -> None:
    """Collect papers from OpenReview.

    Best for: ICLR, NeurIPS, ICML with complete paper metadata and reviews.

    By default, only accepted papers are collected. Use --include-rejected
    to collect all submissions including rejected and withdrawn papers.

    Examples:

      # Collect from ICLR (accepted papers only)
      python -m src.cli.core_collect collect-openreview --venue iclr

      # Collect from NeurIPS from 2022 onwards
      python -m src.cli.core_collect collect-openreview --venue neurips --since-year 2022

      # Collect all submissions including rejected
      python -m src.cli.core_collect collect-openreview --venue iclr --include-rejected

      # Collect from all OpenReview venues
      python -m src.cli.core_collect collect-openreview --all
    """
    if not any([venue, collect_all]):
        click.echo("Error: Specify --venue or --all")
        click.echo(f"Available OpenReview venues: {', '.join(get_openreview_venues())}")
        sys.exit(1)

    accepted_only = not include_rejected

    async def run_collection() -> int:
        storage = QdrantStorage()
        storage.ensure_collection()

        async with OpenReviewCollector(storage=storage) as collector:
            if collect_all:
                return await collector.collect_all(since_year, to_year, accepted_only=accepted_only)
            elif venue:
                venue_lower = venue.lower()
                if venue_lower not in OPENREVIEW_VENUES:
                    click.echo(f"Error: Unknown OpenReview venue '{venue}'")
                    click.echo(f"Available venues: {', '.join(get_openreview_venues())}")
                    sys.exit(1)

                total = 0
                async for batch in collector.collect_venue(
                    venue_lower, since_year, to_year, accepted_only=accepted_only
                ):
                    total += len(batch)
                    click.echo(f"Collected {total} papers from OpenReview {venue}")
                return total

        return 0

    total = asyncio.run(run_collection())
    click.echo(f"\nOpenReview collection complete: {total} papers")


@cli.command("list-openreview-venues")
def list_openreview_venues() -> None:
    """List available OpenReview venues."""
    click.echo("\n=== OpenReview Venues ===\n")
    click.echo(f"{'Name':12} {'Tier':6} {'Start Year':12} {'Full Name'}")
    click.echo("-" * 80)

    for name, info in OPENREVIEW_VENUES.items():
        click.echo(f"{name:12} {info['tier']:6} {info['start_year']:12} {info['full_name']}")

    click.echo(f"\nTotal: {len(OPENREVIEW_VENUES)} venues")


# ============================================================================
# ACM Open Commands
# ============================================================================


@cli.command("collect-acm")
@click.option("--venue", "-V", help="ACM venue name (e.g., kdd, sigir, www)")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--all", "collect_all", is_flag=True, help="Collect from all ACM venues")
@click.option("--no-abstracts", is_flag=True, help="Skip fetching abstracts from ACM DL")
def collect_acm(
    venue: str | None,
    since_year: int,
    to_year: int | None,
    collect_all: bool,
    no_abstracts: bool,
) -> None:
    """Collect papers from ACM Digital Library (now open access).

    Uses DBLP for paper metadata and ACM DL for abstracts.

    Examples:

      # Collect from KDD
      python -m src.cli.core_collect collect-acm --venue kdd

      # Collect from SIGIR from 2022 onwards
      python -m src.cli.core_collect collect-acm --venue sigir --since-year 2022

      # Collect from all ACM venues
      python -m src.cli.core_collect collect-acm --all

      # Fast collection without abstracts
      python -m src.cli.core_collect collect-acm --venue www --no-abstracts
    """
    if not any([venue, collect_all]):
        click.echo("Error: Specify --venue or --all")
        click.echo(f"Available ACM venues: {', '.join(get_acm_open_venues())}")
        sys.exit(1)

    async def run_collection() -> int:
        storage = QdrantStorage()
        storage.ensure_collection()

        async with ACMOpenCollector(
            storage=storage,
            fetch_abstracts=not no_abstracts
        ) as collector:
            if collect_all:
                return await collector.collect_all(since_year, to_year)
            elif venue:
                venue_lower = venue.lower()
                if venue_lower not in ACM_OPEN_VENUES:
                    click.echo(f"Error: Unknown ACM venue '{venue}'")
                    click.echo(f"Available venues: {', '.join(get_acm_open_venues())}")
                    sys.exit(1)

                total = 0
                async for batch in collector.collect_venue(venue_lower, since_year, to_year):
                    total += len(batch)
                    click.echo(f"Collected {total} papers from ACM {venue}")
                return total

        return 0

    total = asyncio.run(run_collection())
    click.echo(f"\nACM collection complete: {total} papers")


@cli.command("list-acm-venues")
def list_acm_venues() -> None:
    """List available ACM venues."""
    click.echo("\n=== ACM Open Venues ===\n")
    click.echo(f"{'Name':12} {'Tier':6} {'Full Name'}")
    click.echo("-" * 80)

    for name, info in ACM_OPEN_VENUES.items():
        click.echo(f"{name:12} {info['tier']:6} {info['full_name']}")

    click.echo(f"\nTotal: {len(ACM_OPEN_VENUES)} venues")


# ============================================================================
# AAAI OJS Commands
# ============================================================================


@cli.command("collect-aaai")
@click.option("--venue", "-V", help="AAAI venue name (e.g., aaai, icwsm)")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--all", "collect_all", is_flag=True, help="Collect from all AAAI venues")
def collect_aaai(
    venue: str | None,
    since_year: int,
    to_year: int | None,
    collect_all: bool,
) -> None:
    """Collect papers from AAAI OJS platform.

    Note: AAAI 2024+ uses OpenReview. Use collect-openreview for recent years.

    Examples:

      # Collect from AAAI
      python -m src.cli.core_collect collect-aaai --venue aaai

      # Collect from AAAI 2020-2023
      python -m src.cli.core_collect collect-aaai --since-year 2020 --to-year 2023

      # Collect from all AAAI venues
      python -m src.cli.core_collect collect-aaai --all
    """
    if not any([venue, collect_all]):
        click.echo("Error: Specify --venue or --all")
        click.echo(f"Available AAAI venues: {', '.join(get_aaai_venues())}")
        sys.exit(1)

    async def run_collection() -> int:
        storage = QdrantStorage()
        storage.ensure_collection()

        async with AAOJSCollector(storage=storage) as collector:
            if collect_all:
                return await collector.collect_all(since_year, to_year)
            elif venue:
                venue_lower = venue.lower()
                if venue_lower not in AAAI_VENUES:
                    click.echo(f"Error: Unknown AAAI venue '{venue}'")
                    click.echo(f"Available venues: {', '.join(get_aaai_venues())}")
                    sys.exit(1)

                total = 0
                async for batch in collector.collect_venue(venue_lower, since_year, to_year):
                    total += len(batch)
                    click.echo(f"Collected {total} papers from AAAI {venue}")
                return total

        return 0

    total = asyncio.run(run_collection())
    click.echo(f"\nAAI OJS collection complete: {total} papers")


@cli.command("list-aaai-venues")
def list_aaai_venues() -> None:
    """List available AAAI OJS venues."""
    click.echo("\n=== AAAI OJS Venues ===\n")
    click.echo(f"{'Name':12} {'Tier':6} {'Full Name'}")
    click.echo("-" * 70)

    for name, info in AAAI_VENUES.items():
        click.echo(f"{name:12} {info['tier']:6} {info['full_name']}")

    click.echo(f"\nTotal: {len(AAAI_VENUES)} venues")
    click.echo("\nNote: AAAI 2024+ uses OpenReview. Use 'list-openreview-venues' for recent years.")


# ============================================================================
# Multi-Source Commands
# ============================================================================


@cli.command("collect-all-sources")
@click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
@click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
@click.option("--since-date", type=str, help="Start date in YYYY-MM or YYYY-MM-DD format (overrides --since-year)")
@click.option("--to-date", type=str, help="End date in YYYY-MM or YYYY-MM-DD format (overrides --to-year)")
@click.option("--skip-openalex", is_flag=True, help="Skip OpenAlex collection")
@click.option("--skip-acl", is_flag=True, help="Skip ACL Anthology collection")
@click.option("--skip-dblp", is_flag=True, help="Skip DBLP collection")
@click.option("--skip-openreview", is_flag=True, help="Skip OpenReview collection")
@click.option("--skip-acm", is_flag=True, help="Skip ACM Open collection")
@click.option("--skip-aaai", is_flag=True, help="Skip AAAI OJS collection")
@click.option("--include-workshops", is_flag=True, help="Include ACL workshop papers")
@click.option("--dry-run", is_flag=True, help="Fetch papers but don't save to storage (output to JSON)")
@click.option("--output", "-o", type=click.Path(), help="Output JSON file path (for dry-run)")
@click.option("--collection", "-c", type=str, help="Qdrant collection name (default: lexicon_arxiv or QDRANT_COLLECTION env)")
def collect_all_sources(
    since_year: int,
    to_year: int | None,
    since_date: str | None,
    to_date: str | None,
    skip_openalex: bool,
    skip_acl: bool,
    skip_dblp: bool,
    skip_openreview: bool,
    skip_acm: bool,
    skip_aaai: bool,
    include_workshops: bool,
    dry_run: bool,
    output: str | None,
    collection: str | None,
) -> None:
    """Collect papers from all sources (OpenAlex, ACL, DBLP, OpenReview, ACM, AAAI).

    This is the main command for building the complete core corpus.
    Papers are deduplicated across sources.

    Examples:

      # Collect from all sources
      python -m src.cli.core_collect collect-all-sources

      # Collect from 2022 onwards
      python -m src.cli.core_collect collect-all-sources --since-year 2022

      # Collect specific month range (Jan-Mar 2023)
      python -m src.cli.core_collect collect-all-sources --since-date 2023-01 --to-date 2023-03

      # Skip OpenAlex (if already collected)
      python -m src.cli.core_collect collect-all-sources --skip-openalex

      # Collect only new sources
      python -m src.cli.core_collect collect-all-sources --skip-openalex --skip-acl --skip-dblp

      # Dry run: fetch but don't save, output to JSON
      python -m src.cli.core_collect collect-all-sources --dry-run -o papers.json

      # Dry run: year 2020 only, all sources
      python -m src.cli.core_collect collect-all-sources --since-year 2020 --to-year 2020 --dry-run

    Note: DBLP only supports year-level filtering (month is ignored for DBLP).
    """
    # Display date range info
    if since_date or to_date:
        date_range = f"{since_date or f'{since_year}-01'} to {to_date or 'present'}"
    else:
        date_range = f"{since_year} to {to_year or 'present'}"
    click.echo(f"Date range: {date_range}")

    async def run_collection() -> dict[str, int | list]:
        # Only use storage if not dry-run
        storage = None
        if not dry_run:
            storage = QdrantStorage(collection_name=collection) if collection else QdrantStorage()
            storage.ensure_collection()
            click.echo(f"Using Qdrant collection: {storage.collection_name}")

        # Create shared deduplicator for cross-source deduplication
        shared_deduplicator = Deduplicator()
        click.echo("Using shared deduplicator for cross-source deduplication")

        results: dict[str, int | list] = {}
        all_papers: list[dict] = []

        # Collect from OpenAlex (highest priority - richest metadata)
        if not skip_openalex:
            click.echo("\n=== Collecting from OpenAlex ===\n")
            async with CoreCorpusCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                async for batch in collector.collect_all_iter(
                    since_year, to_year,
                    save_to_storage=not dry_run,
                    since_date=since_date, to_date=to_date
                ):
                    if dry_run:
                        all_papers.extend([p.model_dump() for p in batch])
                    total += len(batch)
                    click.echo(f"  Fetched {total} papers...")
                results["openalex"] = total
                click.echo(f"OpenAlex: {total} papers" + (" (not saved)" if dry_run else ""))

        # Collect from ACL Anthology
        if not skip_acl:
            click.echo("\n=== Collecting from ACL Anthology ===\n")
            async with ACLAnthologyCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                for venue in get_acl_venues():
                    async for batch in collector.collect_venue(
                        venue, since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  {venue}: {total} papers so far...")

                # Collect workshops if enabled
                if include_workshops:
                    click.echo("  Collecting workshops...")
                    async for batch in collector.collect_workshops(
                        since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  workshops: {total} papers so far...")

                results["acl"] = total
                click.echo(f"ACL Anthology: {total} papers" + (" (not saved)" if dry_run else ""))

        # Collect from DBLP
        if not skip_dblp:
            click.echo("\n=== Collecting from DBLP ===\n")
            if since_date or to_date:
                click.echo("  Note: DBLP only supports year-level filtering")
            async with DBLPCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                for venue in get_dblp_venues():
                    async for batch in collector.collect_venue(
                        venue, since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  {venue}: {total} papers so far...")
                results["dblp"] = total
                click.echo(f"DBLP: {total} papers" + (" (not saved)" if dry_run else ""))

        # Collect from OpenReview (accepted papers only by default)
        if not skip_openreview:
            click.echo("\n=== Collecting from OpenReview ===\n")
            async with OpenReviewCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                for venue in get_openreview_venues():
                    async for batch in collector.collect_venue(
                        venue, since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date,
                        accepted_only=True,  # Only accepted papers
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  {venue}: {total} papers so far...")
                results["openreview"] = total
                click.echo(f"OpenReview: {total} papers" + (" (not saved)" if dry_run else ""))

        # Collect from ACM Open
        if not skip_acm:
            click.echo("\n=== Collecting from ACM Open ===\n")
            async with ACMOpenCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                for venue in get_acm_open_venues():
                    async for batch in collector.collect_venue(
                        venue, since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  {venue}: {total} papers so far...")
                results["acm"] = total
                click.echo(f"ACM Open: {total} papers" + (" (not saved)" if dry_run else ""))

        # Collect from AAAI OJS
        if not skip_aaai:
            click.echo("\n=== Collecting from AAAI OJS ===\n")
            async with AAOJSCollector(
                storage=storage,
                deduplicator=shared_deduplicator,
            ) as collector:
                total = 0
                for venue in get_aaai_venues():
                    async for batch in collector.collect_venue(
                        venue, since_year, to_year,
                        save_to_storage=not dry_run,
                        since_date=since_date, to_date=to_date
                    ):
                        if dry_run:
                            all_papers.extend([p.model_dump() for p in batch])
                        total += len(batch)
                    click.echo(f"  {venue}: {total} papers so far...")
                results["aaai"] = total
                click.echo(f"AAAI OJS: {total} papers" + (" (not saved)" if dry_run else ""))

        # Report deduplication stats
        dedup_stats = shared_deduplicator.stats
        click.echo(f"\nDeduplication stats: {dedup_stats['title_years']} unique papers tracked")

        if dry_run:
            results["_papers"] = all_papers

        return results

    results = asyncio.run(run_collection())

    click.echo("\n=== Collection Summary ===\n")
    total = 0
    for source, count in results.items():
        if source != "_papers":
            click.echo(f"  {source:12}: {count:>6} papers")
            total += count
    click.echo(f"\n  {'Total':12}: {total:>6} papers")

    # Output JSON for dry-run
    if dry_run and "_papers" in results:
        papers = results["_papers"]
        if output:
            output_path = output
        elif since_date or to_date:
            start = since_date or f"{since_year}-01"
            end = to_date or "present"
            output_path = f"papers_{start}_{end}.json"
        else:
            output_path = f"papers_{since_year}_{to_year or 'present'}.json"
        with open(output_path, "w") as f:
            json.dump(papers, f, indent=2, default=str)
        click.echo(f"\n  Output saved to: {output_path}")
        click.echo(f"  Total papers in file: {len(papers)}")
    elif not dry_run:
        # Show Qdrant count
        try:
            storage = QdrantStorage()
            db_count = storage.count_papers()
            click.echo(f"\n  Papers in Qdrant: {db_count}")
        except Exception:
            pass


# ============================================================================
# Post-Collection Deduplication Commands
# ============================================================================


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


# ============================================================================
# Data Quality & Enrichment Commands
# ============================================================================


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


@cli.command("enrich-citations")
@click.option("--dry-run", is_flag=True, help="Count papers without enriching")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--batch-size", type=int, default=100, help="Batch size")
@click.option("--delay", type=float, default=0.1, help="Delay between API calls")
@click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
def enrich_citations(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    delay: float,
    parallel: int,
) -> None:
    """Enrich papers with citation data from OpenAlex.

    Fetches referenced_works for papers that have DOI but missing citations.
    Progress is checkpointed for resumable operation.

    Examples:

      # Count papers needing enrichment
      python -m src.cli.core_collect enrich-citations --dry-run

      # Enrich all papers
      python -m src.cli.core_collect enrich-citations

      # Enrich with parallel requests (faster)
      python -m src.cli.core_collect enrich-citations --parallel 10

      # Enrich first 1000 papers
      python -m src.cli.core_collect enrich-citations --limit 1000
    """
    from src.core.enrichment.openalex import PaperEnricher

    async def run_enrichment():
        storage = QdrantStorage()
        async with PaperEnricher(
            storage=storage,
            batch_size=batch_size,
            delay=delay,
            max_concurrent=parallel,
        ) as enricher:
            progress = await enricher.enrich_citations(dry_run=dry_run, limit=limit)

            click.echo(f"\nCitation Enrichment Results:")
            click.echo(f"  Processed: {progress.processed}")
            click.echo(f"  Enriched:  {progress.enriched}")
            click.echo(f"  Not found: {progress.not_found}")
            click.echo(f"  Errors:    {progress.errors}")

            if dry_run:
                click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                click.echo("  (Dry run - no changes made)")

    asyncio.run(run_enrichment())


@cli.command("enrich-abstracts")
@click.option("--dry-run", is_flag=True, help="Count papers without enriching")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--batch-size", type=int, default=100, help="Batch size")
@click.option("--delay", type=float, default=0.1, help="Delay between API calls")
@click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
def enrich_abstracts(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    delay: float,
    parallel: int,
) -> None:
    """Enrich papers with abstracts from OpenAlex.

    Fetches abstracts for papers that have DOI but missing abstracts.
    Progress is checkpointed for resumable operation.

    Examples:

      # Count papers needing abstract enrichment
      python -m src.cli.core_collect enrich-abstracts --dry-run

      # Enrich all papers
      python -m src.cli.core_collect enrich-abstracts

      # Enrich with parallel requests (faster)
      python -m src.cli.core_collect enrich-abstracts --parallel 10

      # Enrich first 100 papers
      python -m src.cli.core_collect enrich-abstracts --limit 100
    """
    from src.core.enrichment.openalex import PaperEnricher

    async def run_enrichment():
        storage = QdrantStorage()
        async with PaperEnricher(
            storage=storage,
            batch_size=batch_size,
            delay=delay,
            max_concurrent=parallel,
        ) as enricher:
            progress = await enricher.enrich_abstracts(dry_run=dry_run, limit=limit)

            click.echo(f"\nAbstract Enrichment Results:")
            click.echo(f"  Processed: {progress.processed}")
            click.echo(f"  Enriched:  {progress.enriched}")
            click.echo(f"  Not found: {progress.not_found}")
            click.echo(f"  Errors:    {progress.errors}")

            if dry_run:
                click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                click.echo("  (Dry run - no changes made)")

    asyncio.run(run_enrichment())


@cli.command("enrich-citations-by-title")
@click.option("--dry-run", is_flag=True, help="Count papers without enriching")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--batch-size", type=int, default=100, help="Batch size")
@click.option("--delay", type=float, default=0.1, help="Delay between API calls")
@click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
@click.option("--venue", "-v", multiple=True, help="Filter by venue (can repeat)")
@click.option("--min-refs", type=int, default=1, help="Minimum refs required for match")
def enrich_citations_by_title(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    delay: float,
    parallel: int,
    venue: tuple[str, ...],
    min_refs: int,
) -> None:
    """Enrich papers WITHOUT DOIs by searching OpenAlex by title.

    This is useful for OpenReview papers (NeurIPS, ICML, ICLR) that
    don't have DOIs but may have arXiv versions indexed in OpenAlex.

    The search only returns matches that have at least --min-refs references.

    Examples:

      # Count papers needing title-based enrichment
      python -m src.cli.core_collect enrich-citations-by-title --dry-run

      # Enrich all papers without DOIs
      python -m src.cli.core_collect enrich-citations-by-title

      # Enrich only NeurIPS papers
      python -m src.cli.core_collect enrich-citations-by-title -v "NeurIPS 2024 poster"

      # Enrich with parallel requests
      python -m src.cli.core_collect enrich-citations-by-title --parallel 5

      # Only accept matches with 5+ references
      python -m src.cli.core_collect enrich-citations-by-title --min-refs 5
    """
    from src.core.enrichment.openalex import PaperEnricher

    venues_list = list(venue) if venue else None

    async def run_enrichment():
        storage = QdrantStorage()
        async with PaperEnricher(
            storage=storage,
            batch_size=batch_size,
            delay=delay,
            max_concurrent=parallel,
        ) as enricher:
            progress = await enricher.enrich_citations_by_title(
                dry_run=dry_run,
                limit=limit,
                venues=venues_list,
                min_refs=min_refs,
            )

            click.echo(f"\nTitle-Based Citation Enrichment Results:")
            click.echo(f"  Processed: {progress.processed}")
            click.echo(f"  Enriched:  {progress.enriched}")
            click.echo(f"  Not found: {progress.not_found}")
            click.echo(f"  Errors:    {progress.errors}")

            if dry_run:
                click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                click.echo("  (Dry run - no changes made)")

    asyncio.run(run_enrichment())


@cli.command("clear-enrichment-checkpoint")
@click.option("--type", "enrichment_type", type=click.Choice(["citations", "abstracts", "title_citations", "all"]),
              default="all", help="Type of checkpoint to clear")
def clear_enrichment_checkpoint(enrichment_type: str) -> None:
    """Clear enrichment checkpoint for fresh start.

    Examples:

      # Clear all checkpoints
      python -m src.cli.core_collect clear-enrichment-checkpoint

      # Clear only citation checkpoint
      python -m src.cli.core_collect clear-enrichment-checkpoint --type citations

      # Clear only abstract checkpoint
      python -m src.cli.core_collect clear-enrichment-checkpoint --type abstracts

      # Clear only title-based citation checkpoint
      python -m src.cli.core_collect clear-enrichment-checkpoint --type title_citations
    """
    from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

    enricher = PaperEnricher()

    if enrichment_type in ("citations", "all"):
        enricher.clear_checkpoint(EnrichmentType.CITATIONS)
        click.echo("Citation enrichment checkpoint cleared.")

    if enrichment_type in ("abstracts", "all"):
        enricher.clear_checkpoint(EnrichmentType.ABSTRACTS)
        click.echo("Abstract enrichment checkpoint cleared.")

    if enrichment_type in ("title_citations", "all"):
        enricher.clear_checkpoint(EnrichmentType.TITLE_CITATIONS)
        click.echo("Title-based citation enrichment checkpoint cleared.")


# =============================================================================
# Semantic Scholar Enrichment
# =============================================================================


@cli.command("enrich-s2")
@click.option("--dry-run", is_flag=True, help="Count papers without enriching")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--batch-size", type=int, default=50, help="Batch size")
@click.option("--delay", type=float, default=None, help="Delay between API calls (auto: 1.1s with key, 3s without)")
@click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 1 with key, 1 without)")
@click.option("--by-title", is_flag=True, help="Search by title instead of DOI")
@click.option("--venue", "-v", multiple=True, help="Filter by venue (for title search)")
@click.option("--min-refs", type=int, default=1, help="Min refs required (for title search)")
def enrich_s2(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    delay: float | None,
    parallel: int | None,
    by_title: bool,
    venue: tuple[str, ...],
    min_refs: int,
) -> None:
    """Enrich citations using Semantic Scholar API.

    S2 often has better coverage for ML/AI papers than OpenAlex.
    Use this as a fallback when OpenAlex enrichment fails.

    API Key (optional but recommended):
      Set S2_API_KEY env var for ~3x faster processing.
      Get a free key at: https://www.semanticscholar.org/product/api#api-key

    Rate Limits (auto-adjusted based on API key):
      Without key: ~20 req/min (conservative)
      With key: ~55 req/min (1 req/sec cumulative limit)

    Examples:

      # Enrich papers with DOIs (fallback after OpenAlex)
      python -m src.cli.core_collect enrich-s2

      # With API key for faster processing
      S2_API_KEY=your_key python -m src.cli.core_collect enrich-s2

      # Enrich papers without DOIs by title search
      python -m src.cli.core_collect enrich-s2 --by-title

      # Target specific venues
      python -m src.cli.core_collect enrich-s2 --by-title -v "NeurIPS 2024 poster"
    """
    from src.core.enrichment.semantic_scholar import SemanticScholarEnricher

    venues_list = list(venue) if venue else None

    async def run_enrichment():
        storage = QdrantStorage()
        async with SemanticScholarEnricher(
            storage=storage,
            batch_size=batch_size,
            delay=delay,
            max_concurrent=parallel,
        ) as enricher:
            if by_title:
                progress = await enricher.enrich_by_title(
                    dry_run=dry_run,
                    limit=limit,
                    venues=venues_list,
                    min_refs=min_refs,
                )
            else:
                progress = await enricher.enrich_by_doi(
                    dry_run=dry_run,
                    limit=limit,
                )

            click.echo(f"\nSemantic Scholar Enrichment Results:")
            click.echo(f"  Processed: {progress.processed}")
            click.echo(f"  Enriched:  {progress.enriched}")
            click.echo(f"  Not found: {progress.not_found}")
            if hasattr(progress, 'no_refs'):
                click.echo(f"  No refs:   {progress.no_refs}")
            click.echo(f"  Errors:    {progress.errors}")

            if dry_run:
                click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                click.echo("  (Dry run - no changes made)")

    asyncio.run(run_enrichment())


@cli.command("clear-s2-checkpoint")
@click.option("--type", "checkpoint_type", type=click.Choice(["doi", "title", "all"]),
              default="all", help="Type of S2 checkpoint to clear")
def clear_s2_checkpoint(checkpoint_type: str) -> None:
    """Clear Semantic Scholar enrichment checkpoint.

    Examples:

      # Clear all S2 checkpoints
      python -m src.cli.core_collect clear-s2-checkpoint

      # Clear only DOI-based checkpoint
      python -m src.cli.core_collect clear-s2-checkpoint --type doi

      # Clear only title-based checkpoint
      python -m src.cli.core_collect clear-s2-checkpoint --type title
    """
    from src.core.enrichment.semantic_scholar import SemanticScholarEnricher

    enricher = SemanticScholarEnricher()

    if checkpoint_type in ("doi", "all"):
        enricher.clear_checkpoint(by_title=False)
        click.echo("Semantic Scholar DOI checkpoint cleared.")

    if checkpoint_type in ("title", "all"):
        enricher.clear_checkpoint(by_title=True)
        click.echo("Semantic Scholar title checkpoint cleared.")


# =============================================================================
# PDF Reference Extraction
# =============================================================================


@cli.command("extract-pdf-refs")
@click.option("--dry-run", is_flag=True, help="Count papers without extracting")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--batch-size", type=int, default=10, help="Batch size (keep small for PDFs)")
@click.option("--parallel", "-p", type=int, default=2, help="Concurrent extractions")
@click.option("--venue", "-v", multiple=True, help="Filter by venue")
@click.option("--grobid-url", type=str, help="GROBID server URL (default: http://localhost:8070)")
def extract_pdf_refs(
    dry_run: bool,
    limit: int | None,
    batch_size: int,
    parallel: int,
    venue: tuple[str, ...],
    grobid_url: str | None,
) -> None:
    """Extract references from PDFs using GROBID.

    This is a last-resort method when API-based enrichment fails.
    It downloads PDFs and extracts reference sections using GROBID.

    GROBID must be running:
      docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

    Examples:

      # Count papers with PDF URLs
      python -m src.cli.core_collect extract-pdf-refs --dry-run

      # Extract from all PDFs
      python -m src.cli.core_collect extract-pdf-refs

      # Target specific venues
      python -m src.cli.core_collect extract-pdf-refs -v "NeurIPS 2024 poster"
    """
    from src.core.enrichment.pdf import PDFReferenceExtractor

    venues_list = list(venue) if venue else None

    async def run_extraction():
        storage = QdrantStorage()
        async with PDFReferenceExtractor(
            storage=storage,
            grobid_url=grobid_url,
            batch_size=batch_size,
            max_concurrent=parallel,
        ) as extractor:
            progress = await extractor.enrich_from_pdfs(
                dry_run=dry_run,
                limit=limit,
                venues=venues_list,
            )

            click.echo(f"\nPDF Reference Extraction Results:")
            click.echo(f"  Processed:       {progress.processed}")
            click.echo(f"  Extracted:       {progress.extracted}")
            click.echo(f"  Download failed: {progress.download_failed}")
            click.echo(f"  Parse failed:    {progress.parse_failed}")
            click.echo(f"  No refs found:   {progress.no_refs}")
            click.echo(f"  Errors:          {progress.errors}")

            if dry_run:
                click.echo(f"\n  Total papers to process: {progress.total_to_process}")
                click.echo("  (Dry run - no changes made)")

    asyncio.run(run_extraction())


@cli.command("clear-pdf-checkpoint")
def clear_pdf_checkpoint() -> None:
    """Clear PDF extraction checkpoint."""
    from src.core.enrichment.pdf import PDFReferenceExtractor

    extractor = PDFReferenceExtractor()
    extractor.clear_checkpoint()
    click.echo("PDF extraction checkpoint cleared.")


# =============================================================================
# Reference Resolution Commands
# =============================================================================


@cli.command("resolve-refs")
@click.option("--dry-run", is_flag=True, help="Count papers without updating")
@click.option("--limit", "-n", type=int, help="Max papers to process")
@click.option("--step", type=click.Choice(["all", "normalize", "arxiv", "internal"]),
              default="all", help="Run specific step only")
@click.option("--fuzzy-matching", is_flag=True, help="Use fuzzy title matching (slower)")
@click.option("--external-search", is_flag=True, help="Search external APIs for unresolved titles")
@click.option("--batch-size", type=int, default=100, help="Batch size")
@click.option("--parallel", "-p", type=int, default=5, help="Concurrent requests")
def resolve_refs(
    dry_run: bool,
    limit: int | None,
    step: str,
    fuzzy_matching: bool,
    external_search: bool,
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
                )
                click.echo(f"\nInternal ID Resolution Results:")
                click.echo(f"  Processed:         {progress.processed}")
                click.echo(f"  Updated:           {progress.updated}")
                click.echo(f"  DOIs resolved:     {progress.dois_resolved}")
                click.echo(f"  OpenAlex resolved: {progress.openalex_resolved}")
                click.echo(f"  Titles resolved:   {progress.titles_resolved}")
                if progress.external_added > 0:
                    click.echo(f"  External added:    {progress.external_added}")

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


# =============================================================================
# Citation Graph Commands
# =============================================================================


@cli.command("build-citation-graph")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--format", "-f", type=click.Choice(["json", "csv", "graphml", "gexf"]),
              default="json", help="Export format (default: json)")
@click.option("--venue", "-v", multiple=True, help="Filter by venue (can repeat)")
@click.option("--year-start", type=int, help="Filter papers from this year")
@click.option("--year-end", type=int, help="Filter papers until this year")
@click.option("--no-metadata", is_flag=True, help="Don't include paper metadata in export")
@click.option("--streaming", is_flag=True, help="Use streaming export (low memory, CSV only)")
def build_citation_graph(
    output: str | None,
    format: str,
    venue: tuple[str, ...],
    year_start: int | None,
    year_end: int | None,
    no_metadata: bool,
    streaming: bool,
) -> None:
    """Build and export the citation graph.

    Creates a directed graph from resolved_references where edges point
    from citing papers to cited papers (A cites B means edge A->B).

    For large graphs (>1M edges), use --streaming to avoid memory issues.
    Streaming mode exports CSV files directly without loading the full graph.

    Examples:

      # Build and export to JSON
      python -m src.cli.core_collect build-citation-graph -o graph.json

      # Export for Gephi
      python -m src.cli.core_collect build-citation-graph -o graph.graphml --format graphml

      # Filter by venue
      python -m src.cli.core_collect build-citation-graph -v ACL -v EMNLP -o nlp_graph.json

      # Filter by year range
      python -m src.cli.core_collect build-citation-graph --year-start 2020 --year-end 2023 -o recent.json

      # Large graph: use streaming export (low memory)
      python -m src.cli.core_collect build-citation-graph -o /tmp/graph --streaming
    """
    from src.core.citation_graph import CitationGraphBuilder, GraphExporter, StreamingGraphExporter, estimate_memory_mb

    click.echo("\n=== Building Citation Graph ===\n")

    storage = QdrantStorage()

    # Streaming mode: export directly from Qdrant
    if streaming:
        if venue or year_start or year_end:
            click.echo("Warning: Filters are not supported in streaming mode. Exporting full graph.")

        if not output:
            click.echo("Error: --output is required for streaming export")
            sys.exit(1)

        click.echo("Using streaming export (low memory mode)...")
        exporter = StreamingGraphExporter(storage)
        result = exporter.export_csv(
            output_dir=output,
            prefix="citation_graph",
            include_metadata=not no_metadata,
        )

        click.echo(f"\nStreaming export complete:")
        click.echo(f"  Nodes: {result['node_count']:,}")
        click.echo(f"  Edges: {result['edge_count']:,}")
        click.echo(f"  Files: {result['edges_file']}")
        click.echo(f"         {result['nodes_file']}")
        return

    # Check graph size and warn about memory
    stats = storage.get_citation_graph_stats()
    est_memory = estimate_memory_mb(
        stats["total_papers"],
        stats["total_resolved_refs"],
        not no_metadata,
    )

    click.echo(f"Estimated graph size: {stats['total_papers']:,} nodes, {stats['total_resolved_refs']:,} edges")
    click.echo(f"Estimated memory: {est_memory:.0f} MB ({est_memory/1024:.1f} GB)")

    if est_memory > 2000:  # > 2 GB
        click.echo("\nWarning: Large graph may require significant memory.")
        click.echo("Consider using --streaming for memory-efficient CSV export.")
        click.echo("Or use --no-metadata to reduce memory by ~40%.\n")

    builder = CitationGraphBuilder(storage=storage)

    # Build filters
    filter_venues = list(venue) if venue else None
    filter_years = None
    if year_start or year_end:
        filter_years = (year_start or 1900, year_end or 2100)
        click.echo(f"Year filter: {filter_years[0]}-{filter_years[1]}")
    if filter_venues:
        click.echo(f"Venue filter: {', '.join(filter_venues)}")

    # Build graph
    click.echo("Building graph from resolved_references...")
    graph = builder.build_graph(
        filter_venues=filter_venues,
        filter_years=filter_years,
        include_metadata=not no_metadata,
    )

    click.echo(f"\nGraph built:")
    click.echo(f"  Nodes: {graph.number_of_nodes():,}")
    click.echo(f"  Edges: {graph.number_of_edges():,}")

    # Export if output specified
    if output:
        exporter = GraphExporter(graph)
        exporter.export(output, format=format)
        click.echo(f"\nExported to: {output}")
    else:
        click.echo("\nNo output file specified. Use -o to export.")


@cli.command("analyze-citation-graph")
@click.option("--compute-pagerank", is_flag=True, help="Compute PageRank scores")
@click.option("--compute-hits", is_flag=True, help="Compute HITS hub/authority scores")
@click.option("--compute-communities", is_flag=True, help="Detect communities")
@click.option("--all", "compute_all", is_flag=True, help="Compute all metrics")
@click.option("--top-n", type=int, default=10, help="Show top N papers per metric")
@click.option("--store", is_flag=True, help="Store metrics to Qdrant")
@click.option("--pagerank-alpha", type=float, default=0.85, help="PageRank damping factor")
@click.option("--community-resolution", type=float, default=1.0, help="Community detection resolution")
def analyze_citation_graph(
    compute_pagerank: bool,
    compute_hits: bool,
    compute_communities: bool,
    compute_all: bool,
    top_n: int,
    store: bool,
    pagerank_alpha: float,
    community_resolution: float,
) -> None:
    """Analyze the citation graph and compute metrics.

    Computes:
    - PageRank: Paper importance by citation flow
    - HITS: Hub (good surveys) and authority (influential) scores
    - Communities: Research topic clusters

    Examples:

      # Compute all metrics and show top papers
      python -m src.cli.core_collect analyze-citation-graph --all --top-n 50

      # Compute PageRank and store to Qdrant
      python -m src.cli.core_collect analyze-citation-graph --compute-pagerank --store

      # Detect communities
      python -m src.cli.core_collect analyze-citation-graph --compute-communities
    """
    from src.core.citation_graph import CitationGraphBuilder, GraphAnalyzer, estimate_memory_mb

    click.echo("\n=== Analyzing Citation Graph ===\n")

    # Check graph size and warn about memory
    storage = QdrantStorage()
    stats = storage.get_citation_graph_stats()
    est_memory = estimate_memory_mb(
        stats["total_papers"],
        stats["total_resolved_refs"],
        True,  # Analysis needs metadata
    )

    click.echo(f"Estimated graph size: {stats['total_papers']:,} nodes, {stats['total_resolved_refs']:,} edges")
    click.echo(f"Estimated memory: {est_memory:.0f} MB ({est_memory/1024:.1f} GB)")

    if est_memory > 3000:  # > 3 GB
        click.echo("\nWarning: Graph analysis may require significant memory (3+ GB).")
        click.echo("Ensure sufficient RAM is available.\n")

    # Build graph
    builder = CitationGraphBuilder(storage=storage)

    click.echo("Building graph...")
    graph = builder.build_graph(include_metadata=True)

    click.echo(f"Graph: {graph.number_of_nodes():,} nodes, {graph.number_of_edges():,} edges\n")

    if graph.number_of_nodes() == 0:
        click.echo("Graph is empty. Run resolve-refs first to build citation edges.")
        return

    analyzer = GraphAnalyzer(graph, storage=storage)

    # Compute global metrics
    metrics = analyzer.compute_global_metrics()
    click.echo("=== Global Metrics ===\n")
    click.echo(f"  Nodes:                  {metrics.num_nodes:,}")
    click.echo(f"  Edges:                  {metrics.num_edges:,}")
    click.echo(f"  Density:                {metrics.density:.6f}")
    click.echo(f"  Weakly connected:       {'Yes' if metrics.is_weakly_connected else 'No'}")
    click.echo(f"  Weakly connected comps: {metrics.num_weakly_connected_components:,}")
    click.echo(f"  Largest WCC size:       {metrics.largest_wcc_size:,}")
    click.echo(f"  Avg in-degree:          {metrics.avg_in_degree:.2f}")
    click.echo(f"  Avg out-degree:         {metrics.avg_out_degree:.2f}")
    click.echo(f"  Max in-degree:          {metrics.max_in_degree:,}")
    click.echo(f"  Max out-degree:         {metrics.max_out_degree:,}")
    click.echo(f"  Avg clustering:         {metrics.avg_clustering:.4f}")
    click.echo(f"  Reciprocity:            {metrics.reciprocity:.4f}")

    pagerank = None
    hubs = None
    authorities = None
    communities = None

    # Compute PageRank
    if compute_pagerank or compute_all:
        click.echo("\n=== PageRank ===\n")
        pagerank = analyzer.compute_pagerank(alpha=pagerank_alpha)

        top_papers = analyzer.get_top_papers("pagerank", n=top_n, scores=pagerank)
        click.echo(f"Top {top_n} papers by PageRank:\n")
        for i, (paper_id, score, metadata) in enumerate(top_papers, 1):
            title = (metadata.get("title", "")[:60] + "...") if metadata else paper_id[:30]
            year = metadata.get("year", "") if metadata else ""
            click.echo(f"  {i:3}. [{year}] {title}")
            click.echo(f"       PageRank: {score:.6f}  ID: {paper_id[:20]}...")

    # Compute HITS
    if compute_hits or compute_all:
        click.echo("\n=== HITS Scores ===\n")
        hubs, authorities = analyzer.compute_hits()

        click.echo(f"Top {top_n} Hub papers (cite many important papers):\n")
        top_hubs = analyzer.get_top_papers("hub", n=top_n, scores=hubs)
        for i, (paper_id, score, metadata) in enumerate(top_hubs, 1):
            title = (metadata.get("title", "")[:60] + "...") if metadata else paper_id[:30]
            click.echo(f"  {i:3}. Hub: {score:.6f}  {title}")

        click.echo(f"\nTop {top_n} Authority papers (cited by many hubs):\n")
        top_auths = analyzer.get_top_papers("authority", n=top_n, scores=authorities)
        for i, (paper_id, score, metadata) in enumerate(top_auths, 1):
            title = (metadata.get("title", "")[:60] + "...") if metadata else paper_id[:30]
            click.echo(f"  {i:3}. Authority: {score:.6f}  {title}")

    # Compute communities
    if compute_communities or compute_all:
        click.echo("\n=== Communities ===\n")
        communities = analyzer.compute_communities(resolution=community_resolution)

        if communities:
            # Count community sizes
            from collections import Counter
            community_sizes = Counter(communities.values())
            click.echo(f"Detected {len(community_sizes)} communities")
            click.echo(f"\nTop 10 largest communities:")
            for comm_id, size in community_sizes.most_common(10):
                click.echo(f"  Community {comm_id}: {size:,} papers")

    # Store metrics
    if store and (pagerank or hubs or authorities or communities):
        click.echo("\n=== Storing Metrics ===\n")
        updated = analyzer.store_metrics_to_qdrant(
            pagerank=pagerank,
            hubs=hubs,
            authorities=authorities,
            communities=communities,
        )
        click.echo(f"Stored metrics for {updated:,} papers")


@cli.command("citation-graph-stats")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def citation_graph_stats(output_json: bool) -> None:
    """Show citation graph statistics.

    Displays statistics about the citation graph including:
    - Number of papers with references
    - Number of resolved citation edges
    - Resolution coverage

    Examples:

      python -m src.cli.core_collect citation-graph-stats
      python -m src.cli.core_collect citation-graph-stats --json
    """
    try:
        storage = QdrantStorage()
        click.echo("Analyzing citation graph (this may take a moment)...")
        stats = storage.get_citation_graph_stats()
    except Exception as e:
        click.echo(f"Error connecting to Qdrant: {e}")
        sys.exit(1)

    if output_json:
        click.echo(json.dumps(stats, indent=2))
        return

    from src.core.citation_graph import estimate_memory_mb

    click.echo(f"\n{'=' * 50}")
    click.echo("CITATION GRAPH STATISTICS")
    click.echo(f"{'=' * 50}\n")

    click.echo(f"Total papers:                 {stats['total_papers']:,}")
    click.echo(f"Papers with references:       {stats['papers_with_refs']:,}")
    click.echo(f"Papers with resolved refs:    {stats['papers_with_resolved_refs']:,}")
    click.echo(f"Total raw references:         {stats['total_raw_refs']:,}")
    click.echo(f"Total resolved references:    {stats['total_resolved_refs']:,}")
    click.echo(f"Resolution coverage:          {stats['resolution_coverage']:.1f}%")
    click.echo(f"Papers with graph metrics:    {stats['papers_with_graph_metrics']:,}")

    # Memory estimates
    est_with_meta = estimate_memory_mb(stats['total_papers'], stats['total_resolved_refs'], True)
    est_no_meta = estimate_memory_mb(stats['total_papers'], stats['total_resolved_refs'], False)

    click.echo(f"\n=== Memory Estimates ===\n")
    click.echo(f"With metadata:     {est_with_meta:.0f} MB ({est_with_meta/1024:.1f} GB)")
    click.echo(f"Without metadata:  {est_no_meta:.0f} MB ({est_no_meta/1024:.1f} GB)")
    if est_with_meta > 2000:
        click.echo(f"\nTip: Use --streaming for memory-efficient CSV export")


@cli.command("build-cited-by")
def build_cited_by() -> None:
    """Build the cited_by field for all papers (required for GraphRAG).

    Scans all papers' resolved_references and builds a reverse index,
    storing the `cited_by` list in each paper's payload. This enables
    O(1) bidirectional citation traversal for GraphRAG queries.

    After running this command, each paper will have:
    - resolved_references: papers this paper cites
    - cited_by: papers that cite this paper

    Examples:

      python -m src.cli.core_collect build-cited-by
    """
    click.echo("\n=== Building cited_by Index ===\n")
    click.echo("This will scan all papers and compute reverse citations.")
    click.echo("Progress will be logged every 5000 papers.\n")

    storage = QdrantStorage()

    def progress(processed: int, total: int) -> None:
        if processed % 5000 == 0 or processed == total:
            pct = processed / total * 100 if total > 0 else 0
            click.echo(f"  Progress: {processed:,}/{total:,} ({pct:.1f}%)")

    result = storage.build_cited_by_index(progress_callback=progress)

    click.echo(f"\n=== Complete ===\n")
    click.echo(f"Total papers:              {result['total_papers']:,}")
    click.echo(f"Total citation edges:      {result['total_edges']:,}")
    click.echo(f"Papers with citations:     {result['papers_with_citations']:,}")
    click.echo(f"Unique cited papers:       {result['unique_cited_papers']:,}")

    click.echo("\nThe cited_by field is now available for GraphRAG queries.")
    click.echo("Use get-citing-papers <paper_id> to query reverse citations.")


@cli.command("get-citing-papers")
@click.argument("paper_id")
@click.option("--limit", "-n", type=int, default=20, help="Max papers to show")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def get_citing_papers(paper_id: str, limit: int, output_json: bool) -> None:
    """Find papers that cite the given paper.

    PAPER_ID is the Qdrant point ID of the paper.

    Examples:

      python -m src.cli.core_collect get-citing-papers abc123-def456
      python -m src.cli.core_collect get-citing-papers abc123-def456 --limit 50
    """
    from src.core.citation_graph import ReverseCitationIndex

    storage = QdrantStorage()

    # Get the paper info
    paper = storage.get_paper_by_id(paper_id)
    if paper is None:
        click.echo(f"Paper not found: {paper_id}")
        sys.exit(1)

    click.echo(f"\nPaper: {paper.get('title', 'Unknown')[:80]}")
    click.echo(f"Year:  {paper.get('year', 'Unknown')}")
    click.echo(f"Venue: {paper.get('venue', 'Unknown')}")

    # Build reverse index
    click.echo("\nBuilding citation index...")
    index = ReverseCitationIndex(storage)
    index.build_index(include_metadata=True)

    # Get citing papers
    citing_ids = index.get_citing_papers(paper_id)
    click.echo(f"\nFound {len(citing_ids)} papers citing this paper")

    if not citing_ids:
        return

    if output_json:
        results = []
        for cid in citing_ids[:limit]:
            metadata = index.get_paper_metadata(cid)
            results.append({"id": cid, **(metadata or {})})
        click.echo(json.dumps(results, indent=2, default=str))
        return

    click.echo(f"\nShowing top {min(limit, len(citing_ids))} citing papers:\n")
    for i, citing_id in enumerate(citing_ids[:limit], 1):
        metadata = index.get_paper_metadata(citing_id)
        if metadata:
            title = metadata.get("title", "")[:70]
            year = metadata.get("year", "")
            venue = metadata.get("venue", "")[:20]
            click.echo(f"{i:3}. [{year}] {title}")
            click.echo(f"     Venue: {venue}  ID: {citing_id[:30]}...")
        else:
            click.echo(f"{i:3}. {citing_id}")


@cli.command("export-graph-subgraph")
@click.argument("paper_id")
@click.option("--output", "-o", type=click.Path(), required=True, help="Output file path")
@click.option("--hops", type=int, default=2, help="Number of hops from center (default: 2)")
@click.option("--direction", type=click.Choice(["both", "citing", "cited"]),
              default="both", help="Edge direction to follow")
@click.option("--format", "-f", type=click.Choice(["json", "csv", "graphml", "gexf"]),
              default="json", help="Export format")
def export_graph_subgraph(
    paper_id: str,
    output: str,
    hops: int,
    direction: str,
    format: str,
) -> None:
    """Export the citation subgraph around a specific paper.

    Creates a neighborhood graph by traversing citations from the center paper.

    PAPER_ID is the Qdrant point ID of the center paper.

    Examples:

      # Export 2-hop neighborhood
      python -m src.cli.core_collect export-graph-subgraph abc123 -o subgraph.json

      # Export only papers citing this paper (1 hop)
      python -m src.cli.core_collect export-graph-subgraph abc123 -o citing.json --hops 1 --direction citing

      # Export for Gephi
      python -m src.cli.core_collect export-graph-subgraph abc123 -o subgraph.graphml --format graphml
    """
    from src.core.citation_graph import CitationGraphBuilder, GraphExporter

    storage = QdrantStorage()

    # Get the paper info
    paper = storage.get_paper_by_id(paper_id)
    if paper is None:
        click.echo(f"Paper not found: {paper_id}")
        sys.exit(1)

    click.echo(f"\nCenter paper: {paper.get('title', 'Unknown')[:80]}")
    click.echo(f"Year:         {paper.get('year', 'Unknown')}")

    # Build subgraph
    builder = CitationGraphBuilder(storage=storage)

    click.echo(f"\nBuilding {hops}-hop subgraph ({direction} direction)...")
    subgraph = builder.build_subgraph(
        center_paper_id=paper_id,
        hops=hops,
        direction=direction,
        include_metadata=True,
    )

    click.echo(f"Subgraph: {subgraph.number_of_nodes()} nodes, {subgraph.number_of_edges()} edges")

    # Export
    exporter = GraphExporter(subgraph)
    exporter.export(output, format=format)
    click.echo(f"\nExported to: {output}")


# ============================================================================
# Keyword Extraction Commands
# ============================================================================


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


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
