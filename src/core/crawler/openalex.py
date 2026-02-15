"""Core Corpus Collector for venue-based paper collection from OpenAlex.

Collects papers from Tier 0/1 venues using OpenAlex Source ID filtering.
Supports both full collection and incremental updates.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from src.core.checkpoint import CheckpointManager, CollectionCheckpoint
from src.core.config import VenueConfig, get_venue_by_name, get_discovered_venues
from src.core.constants import (
    OPENALEX_BASE_URL,
    get_openalex_api_key,
    get_openalex_email,
)
from src.core.deduplication import Deduplicator
from src.core.openalex_keys import OpenAlexKeyManager
from src.core.storage import QdrantStorage
from src.models.paper import Author, PaperType, RawPaper, SourceType

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# OpenAlex API configuration
DEFAULT_PER_PAGE = 200  # Max allowed by OpenAlex


class CoreCorpusCollector:
    """Collector for Core Corpus papers from OpenAlex.

    Collects papers from configured venues using Source ID filtering,
    with checkpoint support for resumable collection.
    """

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        email: str | None = None,
        api_key: str | None = None,
        key_manager: OpenAlexKeyManager | None = None,
        timeout: float = 30.0,
    ):
        """Initialize the collector.

        Args:
            storage: Qdrant storage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
                Pass a shared instance for cross-source deduplication.
            email: Contact email for OpenAlex polite pool (not needed if api_key provided).
            api_key: OpenAlex API key for higher rate limits.
            key_manager: Shared OpenAlexKeyManager instance. If provided, api_key/email are ignored.
            timeout: HTTP request timeout in seconds.
        """
        self.storage = storage
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()

        # Initialize key manager
        if key_manager:
            self._key_manager = key_manager
        elif api_key:
            self._key_manager = OpenAlexKeyManager(
                [api_key], email or get_openalex_email()
            )
        else:
            self._key_manager = OpenAlexKeyManager.from_env()

        self.timeout = timeout
        self.deduplicator = deduplicator or Deduplicator()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CoreCorpusCollector":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Accept": "application/json",
            "User-Agent": f"LexiconArxiv/1.0 (mailto:{self._key_manager._email or 'unknown'})",
        }
        return headers

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        if self._client is None:
            raise RuntimeError(
                "Collector must be used as async context manager: "
                "async with CoreCorpusCollector() as collector: ..."
            )
        return self._client

    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build API URL with parameters."""
        params.update(self._key_manager.get_next_params())
        query_string = urlencode(params, doseq=True)
        return f"{OPENALEX_BASE_URL}/{endpoint}?{query_string}"

    async def collect_venue(
        self,
        venue: VenueConfig,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a venue.

        Args:
            venue: Venue configuration.
            since_year: Collect papers from this year onwards (ignored if since_date provided).
            to_year: Collect papers until this year (ignored if to_date provided).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format (overrides since_year).
            to_date: End date in YYYY-MM-DD or YYYY-MM format (overrides to_year).

        Yields:
            Batches of collected papers.
        """
        source_ids = venue.all_source_ids
        if not source_ids:
            logger.error(f"Venue {venue.name} has no Source ID, skipping")
            return

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()

        # Check if already complete
        if self.checkpoint_manager.is_venue_complete(checkpoint, venue.name):
            logger.info(f"Venue {venue.name} already complete, skipping")
            return

        # Get resume cursor
        cursor = self.checkpoint_manager.get_resume_cursor(checkpoint, venue.name) or "*"

        # Build source filter - use OR for multiple source IDs
        source_urls = venue.openalex_source_urls
        if len(source_urls) == 1:
            source_filter = f"primary_location.source.id:{source_urls[0]}"
        else:
            # OpenAlex supports OR with pipe: id1|id2|id3
            source_filter = f"primary_location.source.id:{"|".join(source_urls)}"

        # Build date filters - prefer explicit dates over year
        if since_date:
            # Handle YYYY-MM format by appending -01
            from_date = since_date if len(since_date) == 10 else f"{since_date}-01"
        else:
            from_date = f"{since_year}-01-01"

        if to_date:
            # Handle YYYY-MM format by appending last day of month
            if len(to_date) == 7:  # YYYY-MM
                year, month = int(to_date[:4]), int(to_date[5:7])
                import calendar
                last_day = calendar.monthrange(year, month)[1]
                end_date = f"{to_date}-{last_day:02d}"
            else:
                end_date = to_date
        elif to_year:
            end_date = f"{to_year}-12-31"
        else:
            end_date = None

        filters = [
            source_filter,
            f"from_publication_date:{from_date}",
        ]
        if end_date:
            filters.append(f"to_publication_date:{end_date}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(venue.name)
        if progress:
            papers_collected = progress.papers_collected

        source_info = ", ".join(source_ids[:3]) + ("..." if len(source_ids) > 3 else "")
        logger.info(f"Collecting {venue.name} (Sources: {source_info}) from {since_year}")
        if cursor != "*":
            logger.info(f"Resuming from cursor, already have {papers_collected} papers")

        try:
            while True:
                params = {
                    "filter": ",".join(filters),
                    "per-page": DEFAULT_PER_PAGE,
                    "cursor": cursor,
                }

                url = self._build_url("works", params)
                response = await self.client.get(url)
                response.raise_for_status()
                data = response.json()

                checkpoint.total_api_calls += 1

                results = data.get("results", [])
                if not results:
                    break

                # Parse papers
                batch = []
                for work in results:
                    paper = self._parse_work(work, venue)
                    if paper:
                        # Check for duplicates
                        dup_result = self.deduplicator.check_and_add(paper)
                        if not dup_result.is_duplicate:
                            batch.append(paper)

                if batch:
                    if save_to_storage:
                        self.storage.upsert_papers(batch)

                    papers_collected += len(batch)
                    checkpoint.total_papers += len(batch)

                    yield batch

                # Update checkpoint
                next_cursor = data.get("meta", {}).get("next_cursor")
                self.checkpoint_manager.update_venue(
                    checkpoint,
                    venue.name,
                    source_id=venue.source_id,
                    cursor=next_cursor,
                    papers_collected=papers_collected,
                )

                if not next_cursor:
                    break

                cursor = next_cursor

                # Small delay to be nice to the API
                await asyncio.sleep(0.1)

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                venue.name,
                source_id=venue.source_id,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed {venue.name}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting {venue.name}: {e}")
            self.checkpoint_manager.update_venue(
                checkpoint,
                venue.name,
                source_id=venue.source_id,
                papers_collected=papers_collected,
                error=str(e),
            )
            raise

    async def collect_tier(
        self,
        tier: int,
        since_year: int = 2020,
        to_year: int | None = None,
    ) -> int:
        """Collect all papers from venues in a tier.

        Args:
            tier: Tier number (0 or 1).
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year.

        Returns:
            Total number of papers collected.
        """
        from src.core.config import get_tier_venues

        venues = get_tier_venues(tier)
        discovered = [v for v in venues if v.is_discovered]

        if not discovered:
            logger.warning(f"No venues with Source IDs found for tier {tier}")
            return 0

        logger.info(f"Collecting Tier {tier}: {len(discovered)} venues")

        total = 0
        for venue in discovered:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)
                logger.info(f"Tier {tier} progress: {total} papers")

        return total

    async def collect_all(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
    ) -> int:
        """Collect papers from all discovered venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year.

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        if self.storage:
            self.storage.ensure_collection()

        venues = get_discovered_venues()
        logger.info(f"Collecting from {len(venues)} venues")

        total = 0
        for venue in venues:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)

        logger.info(f"Collection complete: {total} papers")
        return total

    async def collect_all_iter(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = False,
        since_date: str | None = None,
        to_date: str | None = None,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from all discovered venues, yielding batches.

        Unlike collect_all(), this yields batches of papers for processing.
        Useful for dry-run mode where we want to inspect papers without saving.

        Args:
            since_year: Collect papers from this year onwards (ignored if since_date provided).
            to_year: Collect papers until this year (ignored if to_date provided).
            save_to_storage: Whether to save to storage (default: False for dry-run).
            since_date: Start date in YYYY-MM-DD or YYYY-MM format.
            to_date: End date in YYYY-MM-DD or YYYY-MM format.

        Yields:
            Batches of collected papers.
        """
        venues = get_discovered_venues()
        logger.info(f"Collecting from {len(venues)} venues (iter mode)")

        for venue in venues:
            async for batch in self.collect_venue(
                venue, since_year, to_year,
                save_to_storage=save_to_storage,
                since_date=since_date, to_date=to_date
            ):
                yield batch

    async def count_venue(
        self,
        venue: VenueConfig,
        since_year: int = 2020,
        to_year: int | None = None,
    ) -> int:
        """Count papers available for a venue without collecting.

        Args:
            venue: Venue configuration.
            since_year: Count papers from this year onwards.
            to_year: Count papers until this year (inclusive).

        Returns:
            Total count of papers available.
        """
        source_ids = venue.all_source_ids
        if not source_ids:
            return 0

        # Build source filter
        source_urls = venue.openalex_source_urls
        if len(source_urls) == 1:
            source_filter = f"primary_location.source.id:{source_urls[0]}"
        else:
            source_filter = f"primary_location.source.id:{"|".join(source_urls)}"

        filters = [
            source_filter,
            f"from_publication_date:{since_year}-01-01",
        ]
        if to_year:
            filters.append(f"to_publication_date:{to_year}-12-31")

        params = {
            "filter": ",".join(filters),
            "per-page": 1,  # We only need the count
        }

        url = self._build_url("works", params)
        response = await self.client.get(url)
        response.raise_for_status()
        data = response.json()

        return data.get("meta", {}).get("count", 0)

    async def count_all(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
    ) -> dict[str, int]:
        """Count papers for all discovered venues without collecting.

        Args:
            since_year: Count papers from this year onwards.
            to_year: Count papers until this year (inclusive).

        Returns:
            Dictionary mapping venue names to paper counts.
        """
        venues = get_discovered_venues()
        counts = {}
        total = 0

        for venue in venues:
            count = await self.count_venue(venue, since_year, to_year)
            counts[venue.name] = count
            total += count
            logger.info(f"{venue.name}: {count:,} papers")
            await asyncio.sleep(0.1)  # Be nice to the API

        counts["_total"] = total
        return counts

    async def collect_incremental(
        self,
        days_back: int = 1,
        save_to_storage: bool = True,
    ) -> int:
        """Collect papers updated in the last N days (for daily cron jobs).

        Uses OpenAlex's from_updated_date filter to fetch only recently
        indexed or updated papers.

        Args:
            days_back: Number of days to look back (default: 1 for daily cron).
            save_to_storage: Whether to save papers to Qdrant.

        Returns:
            Total number of new papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        # Calculate the date to fetch from
        since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        venues = get_discovered_venues()
        logger.info(f"Incremental collection: {len(venues)} venues, updated since {since_date}")

        total_new = 0

        for venue in venues:
            source_ids = venue.all_source_ids
            if not source_ids:
                continue

            # Build source filter
            source_urls = venue.openalex_source_urls
            if len(source_urls) == 1:
                source_filter = f"primary_location.source.id:{source_urls[0]}"
            else:
                source_filter = f"primary_location.source.id:{"|".join(source_urls)}"

            filters = [
                source_filter,
                f"from_updated_date:{since_date}",
            ]

            cursor = "*"
            venue_new = 0

            while True:
                params = {
                    "filter": ",".join(filters),
                    "per-page": DEFAULT_PER_PAGE,
                    "cursor": cursor,
                }

                url = self._build_url("works", params)
                response = await self.client.get(url)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                if not results:
                    break

                # Parse and deduplicate
                batch = []
                for work in results:
                    paper = self._parse_work(work, venue)
                    if paper:
                        dup_result = self.deduplicator.check_and_add(paper)
                        if not dup_result.is_duplicate:
                            batch.append(paper)

                if batch:
                    if save_to_storage:
                        self.storage.upsert_papers(batch)
                    venue_new += len(batch)
                    total_new += len(batch)

                next_cursor = data.get("meta", {}).get("next_cursor")
                if not next_cursor:
                    break

                cursor = next_cursor
                await asyncio.sleep(0.1)

            if venue_new > 0:
                logger.info(f"{venue.name}: {venue_new} new papers")

        logger.info(f"Incremental collection complete: {total_new} new papers")
        return total_new

    def _parse_work(self, work: dict[str, Any], venue: VenueConfig) -> RawPaper | None:
        """Parse OpenAlex work object into RawPaper.

        Args:
            work: OpenAlex work dictionary.
            venue: The venue this paper was collected from.

        Returns:
            Parsed RawPaper or None if parsing fails.
        """
        try:
            # Extract basic info
            openalex_id = (work.get("id") or "").replace("https://openalex.org/", "")
            title = work.get("title") or work.get("display_name", "")

            if not title:
                return None

            # Extract authors
            authors = []
            for authorship in work.get("authorships", []):
                author_data = authorship.get("author", {})
                institutions = authorship.get("institutions", [])

                author = Author(
                    name=author_data.get("display_name") or "Unknown",
                    openalex_id=(author_data.get("id") or "").replace(
                        "https://openalex.org/", ""
                    ),
                    orcid=author_data.get("orcid"),
                    affiliation=institutions[0].get("display_name") if institutions else None,
                )
                authors.append(author)

            # Extract venue from primary_location
            primary_location = work.get("primary_location") or {}
            source = primary_location.get("source") or {}
            venue_name = source.get("display_name") or venue.name
            venue_type = source.get("type") or venue.venue_type

            # Extract DOI
            doi = work.get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")

            # Reconstruct abstract from inverted index
            abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

            # Extract referenced_works (citations)
            referenced_works = [
                ref.replace("https://openalex.org/", "")
                for ref in work.get("referenced_works", [])
                if ref  # Filter out None values
            ]

            # Determine paper type from work type
            paper_type = self._map_paper_type(work.get("type"))

            # Extract categories from concepts
            categories = [
                concept.get("display_name", "")
                for concept in work.get("concepts", [])[:10]
            ]

            return RawPaper(
                source=SourceType.OPENALEX,
                source_id=openalex_id,
                title=title,
                abstract=abstract,
                authors=authors,
                year=work.get("publication_year"),
                doi=doi,
                openalex_id=openalex_id,
                venue=venue_name,
                venue_type=venue_type,
                paper_type=paper_type,
                categories=categories,
                citation_count=work.get("cited_by_count", 0),
                pdf_url=primary_location.get("pdf_url"),
                abstract_url=work.get("id"),
                # Core corpus fields
                tier=venue.tier,
                is_core=True,
                referenced_works=referenced_works,
                raw_data=work,
            )

        except Exception as e:
            logger.warning(f"Failed to parse work: {e}")
            return None

    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index format."""
        if not inverted_index:
            return None

        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))

            word_positions.sort(key=lambda x: x[0])
            return " ".join(word for _, word in word_positions)
        except Exception:
            return None

    def _map_paper_type(self, work_type: str | None) -> PaperType:
        """Map OpenAlex work type to PaperType enum."""
        type_mapping = {
            "article": PaperType.METHOD,
            "review": PaperType.SURVEY,
            "preprint": PaperType.METHOD,
            "dataset": PaperType.DATASET,
            "book-chapter": PaperType.OTHER,
        }
        return type_mapping.get(work_type or "", PaperType.OTHER)


async def discover_source_id(
    venue_name: str,
    email: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Discover OpenAlex Source ID for a venue.

    Args:
        venue_name: Name of the venue to search for.
        email: Contact email for polite pool (not needed if api_key provided).
        api_key: OpenAlex API key for higher rate limits.

    Returns:
        Dictionary with source information.
    """
    # Use API key from env if not provided
    api_key = api_key or get_openalex_api_key()
    email = email or get_openalex_email() if not api_key else None

    params = {"search": venue_name}
    if api_key:
        params["api_key"] = api_key
    elif email:
        params["mailto"] = email

    url = f"{OPENALEX_BASE_URL}/sources?{urlencode(params)}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])

    # Find best match
    matches = []
    for source in results[:10]:
        source_id = source.get("id", "").replace("https://openalex.org/", "")
        matches.append({
            "source_id": source_id,
            "display_name": source.get("display_name"),
            "type": source.get("type"),
            "works_count": source.get("works_count", 0),
            "cited_by_count": source.get("cited_by_count", 0),
        })

    return {
        "query": venue_name,
        "matches": matches,
    }


async def discover_all_missing_sources(email: str | None = None) -> dict[str, Any]:
    """Discover Source IDs for all venues that need discovery.

    Args:
        email: Contact email for polite pool.

    Returns:
        Dictionary mapping venue names to discovered sources.
    """
    from src.core.config import get_undiscovered_venues

    venues = get_undiscovered_venues()
    results = {}

    for venue in venues:
        logger.info(f"Discovering Source ID for {venue.name}")
        result = await discover_source_id(venue.full_name, email)
        results[venue.name] = result
        await asyncio.sleep(0.5)  # Be nice to the API

    return results
