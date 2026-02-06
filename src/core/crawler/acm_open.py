"""ACM Open Library Crawler for ACM conference paper collection.

Collects papers from ACM Digital Library conferences (now fully open access since Jan 2026).
Uses a hybrid DBLP + ACM DL approach: get DOIs from DBLP, fetch abstracts from ACM DL.
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from bs4 import BeautifulSoup

from src.core.checkpoint import CheckpointManager
from src.core.crawler.base import BaseCrawler
from src.core.deduplication import Deduplicator
from src.models.paper import Author, PaperType, RawPaper, SourceType

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# DBLP API endpoint for getting paper metadata
DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"
DBLP_PER_PAGE = 100

# ACM DL base URL for fetching abstracts
ACM_DL_BASE_URL = "https://dl.acm.org"

# Target ACM venues
ACM_VENUES = {
    "kdd": {
        "dblp_key": "conf/kdd",
        "dblp_query": "venue:KDD:",
        "full_name": "ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
        "tier": 0,
    },
    "sigir": {
        "dblp_key": "conf/sigir",
        "dblp_query": "venue:SIGIR:",
        "full_name": "ACM SIGIR Conference on Research and Development in Information Retrieval",
        "tier": 0,
    },
    "www": {
        "dblp_key": "conf/www",
        "dblp_query": "venue:WWW:",
        "full_name": "The Web Conference",
        "tier": 0,
    },
    "recsys": {
        "dblp_key": "conf/recsys",
        "dblp_query": "venue:RecSys:",
        "full_name": "ACM Conference on Recommender Systems",
        "tier": 1,
    },
    "cikm": {
        "dblp_key": "conf/cikm",
        "dblp_query": "venue:CIKM:",
        "full_name": "ACM International Conference on Information and Knowledge Management",
        "tier": 1,
    },
    "wsdm": {
        "dblp_key": "conf/wsdm",
        "dblp_query": "venue:WSDM:",
        "full_name": "ACM International Conference on Web Search and Data Mining",
        "tier": 1,
    },
}


class ACMOpenCollector(BaseCrawler):
    """Collector for papers from ACM conferences via DBLP + ACM DL hybrid.

    Strategy:
    1. Get paper DOIs from DBLP (already structured API)
    2. Fetch abstracts from ACM DL via DOI URLs (now open access!)

    Rate limiting:
    - DBLP: 1 req/sec
    - ACM DL: 0.5 req/sec (conservative for web scraping)
    """

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        timeout: float = 60.0,
        fetch_abstracts: bool = False,  # Disabled by default - ACM blocks scraping
    ):
        """Initialize the collector.

        Args:
            storage: Qdrant storage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
                Pass a shared instance for cross-source deduplication.
            timeout: HTTP request timeout in seconds.
            fetch_abstracts: Whether to fetch abstracts from ACM DL.
        """
        super().__init__(
            storage=storage,
            checkpoint_manager=checkpoint_manager,
            deduplicator=deduplicator,
            timeout=timeout,
            checkpoint_name="acm_open",
        )
        self.fetch_abstracts = fetch_abstracts

    async def __aenter__(self) -> "ACMOpenCollector":
        """Async context manager entry with browser-like headers."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        return self

    def _parse_authors(self, authors_data: Any) -> list[Author]:
        """Parse authors from DBLP response.

        Args:
            authors_data: Authors data from DBLP (can be dict or list).

        Returns:
            List of Author objects.
        """
        authors = []

        if not authors_data:
            return authors

        # DBLP returns single author as dict, multiple as list
        author_list = authors_data.get("author", [])
        if isinstance(author_list, dict):
            author_list = [author_list]

        for author_entry in author_list:
            if isinstance(author_entry, str):
                name = author_entry
            elif isinstance(author_entry, dict):
                name = author_entry.get("text", author_entry.get("@pid", "Unknown"))
            else:
                continue

            # Clean up author name (remove numbers like "0001")
            name = re.sub(r"\s*\d{4}$", "", name).strip()

            authors.append(Author(name=name))

        return authors

    def _determine_paper_type(self, hit: dict[str, Any]) -> PaperType:
        """Determine paper type from DBLP hit.

        Args:
            hit: DBLP search hit dictionary.

        Returns:
            PaperType enum value.
        """
        info = hit.get("info", {})
        title = (info.get("title", "") or "").lower()

        if "survey" in title or "review" in title or "overview" in title:
            return PaperType.SURVEY
        if "dataset" in title or "corpus" in title or "benchmark" in title:
            return PaperType.DATASET
        if "demo" in title or "demonstration" in title:
            return PaperType.DEMO
        if "position" in title or "perspective" in title:
            return PaperType.POSITION
        if "analysis" in title or "study of" in title:
            return PaperType.ANALYSIS

        return PaperType.METHOD

    async def _fetch_abstract_from_acm(self, doi: str) -> str | None:
        """Fetch abstract from ACM DL via DOI.

        Args:
            doi: Paper DOI.

        Returns:
            Abstract text or None if not found.
        """
        if not doi:
            return None

        try:
            # Build ACM DL URL from DOI
            url = f"{ACM_DL_BASE_URL}/doi/{doi}"

            response = await self.client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Try different abstract selectors used by ACM DL
            abstract_elem = soup.select_one("div.abstractSection p")
            if not abstract_elem:
                abstract_elem = soup.select_one("section.abstract p")
            if not abstract_elem:
                abstract_elem = soup.select_one("div.abstractInFull p")
            if not abstract_elem:
                # Try meta tag as fallback
                meta = soup.find("meta", {"name": "description"})
                if meta:
                    return meta.get("content", "").strip()

            if abstract_elem:
                return abstract_elem.get_text(strip=True)

            return None

        except Exception as e:
            logger.debug(f"Failed to fetch abstract for DOI {doi}: {e}")
            return None

    async def _search_dblp(
        self,
        venue: str,
        year: int,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search DBLP for papers from a venue.

        Args:
            venue: Venue name (key in ACM_VENUES).
            year: Publication year.
            offset: Pagination offset.

        Returns:
            Tuple of (list of hits, total count).
        """
        venue_lower = venue.lower()
        if venue_lower not in ACM_VENUES:
            return [], 0

        venue_info = ACM_VENUES[venue_lower]
        query = f"{venue_info['dblp_query']} year:{year}:"

        params = {
            "q": query,
            "format": "json",
            "h": DBLP_PER_PAGE,
            "f": offset,
        }

        try:
            response = await self.client.get(DBLP_SEARCH_URL, params=params)
            response.raise_for_status()
            data = response.json()

            result = data.get("result", {})
            hits_data = result.get("hits", {})
            total = int(hits_data.get("@total", 0))

            hit_list = hits_data.get("hit", [])
            if isinstance(hit_list, dict):
                hit_list = [hit_list]

            return hit_list, total

        except Exception as e:
            logger.error(f"DBLP search failed: {e}")
            return [], 0

    async def _parse_hit(
        self,
        hit: dict[str, Any],
        venue_name: str,
        venue_info: dict[str, Any],
    ) -> RawPaper | None:
        """Parse a DBLP search hit into a RawPaper.

        Args:
            hit: DBLP search hit dictionary.
            venue_name: Short venue name.
            venue_info: Venue info dictionary from ACM_VENUES.

        Returns:
            RawPaper object or None if parsing fails.
        """
        try:
            info = hit.get("info", {})

            # Get title
            title = info.get("title", "")
            if not title:
                return None

            # Clean title (remove trailing period)
            title = title.rstrip(".")

            # Get year
            year_str = info.get("year")
            year = int(year_str) if year_str else None

            # Get authors
            authors = self._parse_authors(info.get("authors"))

            # Get DOI
            doi = info.get("doi")

            # Get URL (electronic edition)
            ee = info.get("ee")
            pdf_url = None
            if ee:
                if isinstance(ee, list):
                    ee = ee[0]
                if isinstance(ee, dict):
                    ee = ee.get("text", ee.get("#text"))
                pdf_url = ee

            # Build abstract URL from DOI
            abstract_url = f"{ACM_DL_BASE_URL}/doi/{doi}" if doi else None

            # Fetch abstract from ACM DL if enabled
            abstract = None
            if self.fetch_abstracts and doi:
                abstract = await self._fetch_abstract_from_acm(doi)
                # Rate limit for ACM DL scraping
                await asyncio.sleep(2.0)

            # Get venue text
            venue_text = info.get("venue", venue_info["full_name"])
            if isinstance(venue_text, list):
                venue_text = venue_text[0] if venue_text else venue_info["full_name"]

            # Determine venue type
            pub_type = info.get("type", "")
            venue_type = "conference"
            if "journal" in pub_type.lower():
                venue_type = "journal"
            elif "workshop" in venue_text.lower():
                venue_type = "workshop"

            # Get DBLP key as source ID
            dblp_key = info.get("key", hit.get("@id", ""))

            # Determine paper type
            paper_type = self._determine_paper_type(hit)

            return RawPaper(
                source=SourceType.ACM,
                source_id=dblp_key,
                title=title,
                abstract=abstract,
                authors=authors,
                year=year,
                doi=doi,
                venue=venue_text,
                venue_type=venue_type,
                paper_type=paper_type,
                pdf_url=pdf_url,
                abstract_url=abstract_url,
                tier=venue_info.get("tier", 0),
                is_core=True,
                raw_data=hit,
            )

        except Exception as e:
            logger.warning(f"Failed to parse DBLP hit: {e}")
            return None

    async def collect_venue(
        self,
        venue: str,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a specific ACM venue.

        Args:
            venue: Venue name (e.g., "kdd", "sigir", "www").
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format.
            to_date: End date in YYYY-MM-DD or YYYY-MM format.

        Yields:
            Batches of collected papers.
        """
        # Parse date constraints
        if since_date:
            since_year = int(since_date[:4])
        if to_date:
            to_year = int(to_date[:4])

        venue_lower = venue.lower()
        if venue_lower not in ACM_VENUES:
            logger.error(f"Unknown ACM venue: {venue}")
            return

        venue_info = ACM_VENUES[venue_lower]

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = f"acm_{venue_lower}"

        # Check if already complete
        if self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info(f"Venue {venue} already complete, skipping")
            return

        logger.info(f"Collecting ACM: {venue} from {since_year}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        # Calculate year range
        import datetime
        current_year = to_year or datetime.datetime.now().year

        try:
            # Collect year by year
            for year in range(since_year, current_year + 1):
                year_offset = 0
                year_total = None

                while True:
                    hits, total = await self._search_dblp(venue, year, year_offset)

                    if year_total is None:
                        year_total = total
                        logger.info(f"ACM {venue} {year}: {total} papers found")

                    if not hits:
                        break

                    # Parse and deduplicate
                    batch = []
                    for hit in hits:
                        paper = await self._parse_hit(hit, venue_lower, venue_info)
                        if paper:
                            dup_result = self.deduplicator.check_and_add(paper)
                            if not dup_result.is_duplicate:
                                batch.append(paper)

                    if batch:
                        if save_to_storage:
                            self.storage.upsert_papers(batch)

                        papers_collected += len(batch)
                        checkpoint.total_papers += len(batch)

                        yield batch

                    year_offset += len(hits)

                    # Update checkpoint
                    self.checkpoint_manager.update_venue(
                        checkpoint,
                        checkpoint_key,
                        cursor=f"{year}:{year_offset}",
                        papers_collected=papers_collected,
                    )

                    # Check if we've collected all papers for this year
                    if year_offset >= year_total:
                        break

                    # Rate limiting for DBLP
                    await asyncio.sleep(1.0)

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed ACM {venue}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting ACM {venue}: {e}")
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                error=str(e),
            )
            raise

    async def collect_all(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
    ) -> int:
        """Collect papers from all ACM venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        logger.info(f"Collecting from {len(ACM_VENUES)} ACM venues")

        total = 0
        for venue in ACM_VENUES:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)

        logger.info(f"ACM collection complete: {total} papers")
        return total


def get_acm_open_venues() -> list[str]:
    """Get list of available ACM venues."""
    return list(ACM_VENUES.keys())


def get_acm_open_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about an ACM venue."""
    return ACM_VENUES.get(venue.lower())
