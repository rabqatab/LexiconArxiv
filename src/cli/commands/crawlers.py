"""Crawler-specific collection commands for LexiconArxiv CLI."""

import asyncio
import json
import logging
import sys

import click

from src.core.deduplication import Deduplicator
from src.core.storage import QdrantStorage
from src.core.crawler import (
    CoreCorpusCollector,
    ACLAnthologyCollector,
    get_acl_venues,
    ACL_VENUES,
    DBLPCollector,
    get_dblp_venues,
    DBLP_VENUES,
    ACM_VENUE_KEYS,
    OpenReviewCollector,
    get_openreview_venues,
    OPENREVIEW_VENUES,
    AAOJSCollector,
    get_aaai_venues,
    AAAI_VENUES,
)

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

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

    @cli.command("collect-dblp")
    @click.option("--venue", "-V", help="DBLP venue name (e.g., recsys, icail, jurix)")
    @click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
    @click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
    @click.option("--all", "collect_all", is_flag=True, help="Collect from all DBLP venues")
    @click.option("--acm-only", is_flag=True, help="Restrict to ACM venues only (KDD, SIGIR, WWW, RecSys, CIKM, WSDM)")
    def collect_dblp(
        venue: str | None,
        since_year: int,
        to_year: int | None,
        collect_all: bool,
        acm_only: bool,
    ) -> None:
        """Collect papers from DBLP.

        Examples:

          # Collect from RecSys
          python -m src.cli.core_collect collect-dblp --venue recsys

          # Collect from ICAIL (legal AI)
          python -m src.cli.core_collect collect-dblp --venue icail --since-year 2020

          # Collect from all DBLP venues
          python -m src.cli.core_collect collect-dblp --all

          # Collect ACM venues only
          python -m src.cli.core_collect collect-dblp --all --acm-only
        """
        if not any([venue, collect_all]):
            click.echo("Error: Specify --venue or --all")
            click.echo(f"Available DBLP venues: {', '.join(get_dblp_venues())}")
            sys.exit(1)

        if venue and acm_only:
            venue_lower = venue.lower()
            if venue_lower not in ACM_VENUE_KEYS:
                click.echo(f"Error: '{venue}' is not an ACM venue")
                click.echo(f"ACM venues: {', '.join(sorted(ACM_VENUE_KEYS))}")
                sys.exit(1)

        async def run_collection() -> int:
            storage = QdrantStorage()
            storage.ensure_collection()

            async with DBLPCollector(storage=storage) as collector:
                if collect_all:
                    if acm_only:
                        # Collect only ACM venues
                        total = 0
                        for v in sorted(ACM_VENUE_KEYS):
                            async for batch in collector.collect_venue(v, since_year, to_year):
                                total += len(batch)
                                click.echo(f"Collected {total} papers from DBLP {v}")
                        return total
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
        click.echo(f"{'Name':12} {'Tier':6} {'ACM':5} {'Full Name'}")
        click.echo("-" * 80)

        for name, info in DBLP_VENUES.items():
            acm_marker = "ACM" if name in ACM_VENUE_KEYS else ""
            click.echo(f"{name:12} {info['tier']:6} {acm_marker:5} {info['full_name']}")

        click.echo(f"\nTotal: {len(DBLP_VENUES)} venues ({len(ACM_VENUE_KEYS)} ACM)")
        click.echo("\nUse --acm-only with collect-dblp to collect only ACM venues.")

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

    @cli.command("collect-all-sources")
    @click.option("--since-year", "-y", default=2020, help="Collect papers from this year (default: 2020)")
    @click.option("--to-year", type=int, help="Collect papers until this year (inclusive)")
    @click.option("--since-date", type=str, help="Start date in YYYY-MM or YYYY-MM-DD format (overrides --since-year)")
    @click.option("--to-date", type=str, help="End date in YYYY-MM or YYYY-MM-DD format (overrides --to-year)")
    @click.option("--skip-openalex", is_flag=True, help="Skip OpenAlex collection")
    @click.option("--skip-acl", is_flag=True, help="Skip ACL Anthology collection")
    @click.option("--skip-dblp", is_flag=True, help="Skip DBLP collection (includes ACM venues)")
    @click.option("--skip-openreview", is_flag=True, help="Skip OpenReview collection")
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
        skip_aaai: bool,
        include_workshops: bool,
        dry_run: bool,
        output: str | None,
        collection: str | None,
    ) -> None:
        """Collect papers from all sources (OpenAlex, ACL, DBLP, OpenReview, AAAI).

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
            # Pass storage so existing Qdrant papers are pre-loaded
            shared_deduplicator = Deduplicator(storage=storage)
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
