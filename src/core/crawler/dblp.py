"""DBLP Crawler for conference paper collection.

Collects papers from DBLP API for:
- ACM conferences (KDD, SIGIR, WWW, RecSys, CIKM, WSDM)
- IR conferences (ECIR)
- Legal AI conferences (ICAIL, JURIX)

Note: DBLP provides metadata only (no abstracts). Use enrichment pipeline
to fill abstracts via Semantic Scholar or OpenAlex.
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.core.checkpoint import CheckpointManager
from src.core.crawler.base import BaseCrawler
from src.core.deduplication import Deduplicator
from src.models.paper import Author, PaperType, RawPaper, SourceType

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# DBLP API endpoints
DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"
DBLP_PER_PAGE = 100  # DBLP default is 30, max is 1000

# All DBLP venues organized by tier
DBLP_VENUES = {
    # Tier 0 - Top-tier ACM conferences
    "kdd": {
        "query": "venue:KDD:",
        "full_name": "ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
        "tier": 0,
    },
    "sigir": {
        "query": "venue:SIGIR:",
        "full_name": "ACM SIGIR Conference on Research and Development in Information Retrieval",
        "tier": 0,
    },
    "www": {
        "query": "venue:WWW:",
        "full_name": "The Web Conference",
        "tier": 0,
    },
    # Tier 1 - Strong conferences
    "recsys": {
        "query": "venue:RecSys:",
        "full_name": "ACM Conference on Recommender Systems",
        "tier": 1,
    },
    "ecir": {
        "query": "venue:ECIR:",
        "full_name": "European Conference on Information Retrieval",
        "tier": 1,
    },
    "cikm": {
        "query": "venue:CIKM:",
        "full_name": "ACM International Conference on Information and Knowledge Management",
        "tier": 1,
    },
    "wsdm": {
        "query": "venue:WSDM:",
        "full_name": "ACM International Conference on Web Search and Data Mining",
        "tier": 1,
    },
    # Tier 2 - Specialized conferences
    "icail": {
        "query": "venue:ICAIL:",
        "full_name": "International Conference on Artificial Intelligence and Law",
        "tier": 2,
    },
    "jurix": {
        "query": "venue:JURIX:",
        "full_name": "International Conference on Legal Knowledge and Information Systems",
        "tier": 2,
    },
}

# Backward compatibility alias
ACM_VENUES = {k: v for k, v in DBLP_VENUES.items() if k in ["kdd", "sigir", "www", "recsys", "cikm", "wsdm"]}


class DBLPCollector(BaseCrawler):
    """Collector for papers from DBLP.

    Uses the DBLP Search API to collect papers from venues
    with poor coverage in other sources.
    """

    DEFAULT_USER_AGENT = "LexiconArxiv/1.0 (DBLP Collection)"

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        timeout: float = 60.0,
    ):
        """Initialize the collector.

        Args:
            storage: Qdrant storage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
                Pass a shared instance for cross-source deduplication.
            timeout: HTTP request timeout in seconds.
        """
        super().__init__(
            storage=storage,
            checkpoint_manager=checkpoint_manager,
            deduplicator=deduplicator,
            timeout=timeout,
            checkpoint_name="dblp",
        )

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
        pub_type = info.get("type", "")

        # Check title for type indicators
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

        # Check publication type
        if pub_type == "Journal Articles":
            return PaperType.METHOD
        if pub_type == "Conference and Workshop Papers":
            return PaperType.METHOD

        return PaperType.METHOD

    def _parse_hit(
        self,
        hit: dict[str, Any],
        venue_name: str,
        venue_info: dict[str, Any],
    ) -> RawPaper | None:
        """Parse a DBLP search hit into a RawPaper.

        Args:
            hit: DBLP search hit dictionary.
            venue_name: Short venue name.
            venue_info: Venue info dictionary from DBLP_VENUES.

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
                    ee = ee[0]  # Take first URL
                if isinstance(ee, dict):
                    ee = ee.get("text", ee.get("#text"))
                pdf_url = ee

            # Get venue from info
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

            # Get DBLP URL
            dblp_url = info.get("url")

            # Determine paper type
            paper_type = self._determine_paper_type(hit)

            return RawPaper(
                source=SourceType.DBLP,
                source_id=dblp_key,
                title=title,
                abstract=None,  # DBLP doesn't provide abstracts
                authors=authors,
                year=year,
                doi=doi,
                venue=venue_text,
                venue_type=venue_type,
                paper_type=paper_type,
                pdf_url=pdf_url,
                abstract_url=dblp_url,
                tier=venue_info.get("tier", 1),
                is_core=True,
                raw_data=hit,
            )

        except Exception as e:
            logger.warning(f"Failed to parse DBLP hit: {e}")
            return None

    async def search_venue(
        self,
        venue: str,
        year: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search DBLP for papers from a venue.

        Args:
            venue: Venue name (key in DBLP_VENUES).
            year: Optional year filter.
            offset: Pagination offset.

        Returns:
            Tuple of (list of hits, total count).
        """
        venue_lower = venue.lower()
        if venue_lower not in DBLP_VENUES:
            return [], 0

        venue_info = DBLP_VENUES[venue_lower]
        query = venue_info["query"]

        # Add year filter if specified
        if year:
            query = f"{query} year:{year}:"

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

            # Get hit list
            hit_list = hits_data.get("hit", [])
            if isinstance(hit_list, dict):
                hit_list = [hit_list]

            return hit_list, total

        except Exception as e:
            logger.error(f"DBLP search failed: {e}")
            return [], 0

    async def collect_venue(
        self,
        venue: str,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a specific DBLP venue.

        Args:
            venue: Venue name (e.g., "recsys", "icail").
            since_year: Collect papers from this year onwards (ignored if since_date provided).
            to_year: Collect papers until this year (ignored if to_date provided).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format (only year used - DBLP API limitation).
            to_date: End date in YYYY-MM-DD or YYYY-MM format (only year used - DBLP API limitation).

        Yields:
            Batches of collected papers.

        Note:
            DBLP API only supports year-level filtering. Month/day from dates are ignored.
        """
        # Parse date constraints (only year is used due to DBLP API limitation)
        if since_date:
            since_year = int(since_date[:4])
        if to_date:
            to_year = int(to_date[:4])
        venue_lower = venue.lower()
        if venue_lower not in DBLP_VENUES:
            logger.error(f"Unknown DBLP venue: {venue}")
            return

        venue_info = DBLP_VENUES[venue_lower]

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = f"dblp_{venue_lower}"

        # Check if already complete
        if self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info(f"Venue {venue} already complete, skipping")
            return

        logger.info(f"Collecting DBLP: {venue} from {since_year}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        # Get resume offset from checkpoint
        current_offset = 0
        if progress and progress.cursor:
            try:
                current_offset = int(progress.cursor)
            except ValueError:
                current_offset = 0

        # Calculate year range
        import datetime
        current_year = to_year or datetime.datetime.now().year

        try:
            # Collect year by year for better pagination control
            for year in range(since_year, current_year + 1):
                year_offset = 0
                year_total = None

                while True:
                    hits, total = await self.search_venue(venue, year, year_offset)

                    if year_total is None:
                        year_total = total
                        logger.info(f"DBLP {venue} {year}: {total} papers found")

                    if not hits:
                        break

                    # Parse and deduplicate
                    batch = []
                    for hit in hits:
                        paper = self._parse_hit(hit, venue_lower, venue_info)
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

                    year_offset += len(hits)
                    current_offset += len(hits)

                    # Update checkpoint
                    self.checkpoint_manager.update_venue(
                        checkpoint,
                        checkpoint_key,
                        cursor=str(current_offset),
                        papers_collected=papers_collected,
                    )

                    # Check if we've collected all papers for this year
                    if year_offset >= year_total:
                        break

                    # Rate limiting - DBLP requests politeness
                    await asyncio.sleep(1.0)

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed DBLP {venue}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting DBLP {venue}: {e}")
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
        """Collect papers from all DBLP venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        logger.info(f"Collecting from {len(DBLP_VENUES)} DBLP venues")

        total = 0
        for venue in DBLP_VENUES:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)

        logger.info(f"DBLP collection complete: {total} papers")
        return total


def get_dblp_venues() -> list[str]:
    """Get list of available DBLP venues."""
    return list(DBLP_VENUES.keys())


def get_dblp_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about a DBLP venue."""
    return DBLP_VENUES.get(venue.lower())


# Backward compatibility aliases for acm_open.py migration
def get_acm_venues() -> list[str]:
    """Get list of ACM venues (subset of DBLP venues)."""
    return list(ACM_VENUES.keys())


def get_acm_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about an ACM venue."""
    return ACM_VENUES.get(venue.lower())


# Alias for backward compatibility
ACMOpenCollector = DBLPCollector
