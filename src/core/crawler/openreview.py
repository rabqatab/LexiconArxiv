"""OpenReview Crawler for ML venue paper collection.

Collects papers from OpenReview API for ICLR, NeurIPS, ICML, and other ML venues.
Uses the official openreview-py Python client.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.core.checkpoint import CheckpointManager
from src.core.crawler.base import BaseCrawler
from src.core.deduplication import Deduplicator
from src.models.paper import Author, PaperType, RawPaper, SourceType

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# OpenReview API endpoints
OPENREVIEW_API_V1 = "https://api.openreview.net"
OPENREVIEW_API_V2 = "https://api2.openreview.net"
OPENREVIEW_PER_PAGE = 1000  # API v2 supports larger batches

# Venue configurations with invitation patterns
# Format: venue_id -> {invitations: year pattern templates, full_name, tier, start_year}
# Note: v2_start_year is venue-specific - different conferences migrated at different times
OPENREVIEW_VENUES = {
    "iclr": {
        # v1 patterns (2013-2023)
        "invitation_pattern_v1": "ICLR.cc/{year}/Conference/-/Blind_Submission",
        "accepted_pattern_v1": "ICLR.cc/{year}/Conference/-/Accept",
        # v2 patterns (2024+) - uses Submission, not Blind_Submission
        "invitation_pattern_v2": "ICLR.cc/{year}/Conference/-/Submission",
        "v2_start_year": 2024,  # ICLR migrated to v2 in 2024
        # Accepted venue values for v2 filtering
        "accepted_venue_patterns": ["{conf} {year} oral", "{conf} {year} spotlight", "{conf} {year} poster"],
        "rejected_venue_patterns": ["Submitted to {conf} {year}", "Withdrawn", "Desk Rejected"],
        "full_name": "International Conference on Learning Representations",
        "conf_name": "ICLR",  # For venue pattern substitution
        "tier": 0,
        "start_year": 2013,
        "conference_month": 5,  # May
    },
    "neurips": {
        # v1 patterns (2021-2022) - 2020 and earlier not on OpenReview
        "invitation_pattern_v1": "NeurIPS.cc/{year}/Conference/-/Blind_Submission",
        "accepted_pattern_v1": "NeurIPS.cc/{year}/Conference/-/Accept",
        # v2 patterns (2023+)
        "invitation_pattern_v2": "NeurIPS.cc/{year}/Conference/-/Submission",
        "v2_start_year": 2023,  # NeurIPS migrated to v2 in 2023
        "accepted_venue_patterns": ["{conf} {year} oral", "{conf} {year} spotlight", "{conf} {year} poster"],
        "rejected_venue_patterns": ["Submitted to {conf} {year}", "Withdrawn", "Desk Rejected"],
        "full_name": "Conference on Neural Information Processing Systems",
        "conf_name": "NeurIPS",
        "tier": 0,
        "start_year": 2021,  # NeurIPS started on OpenReview in 2021
        "conference_month": 12,  # December
    },
    "icml": {
        # v1 patterns (not available for ICML)
        "invitation_pattern_v1": "",  # ICML 2020-2022 not on OpenReview
        "accepted_pattern_v1": "",
        # v2 patterns (2023+)
        "invitation_pattern_v2": "ICML.cc/{year}/Conference/-/Submission",
        "v2_start_year": 2023,  # ICML only available on OpenReview from 2023
        "accepted_venue_patterns": ["{conf} {year} oral", "{conf} {year} spotlight", "{conf} {year} poster"],
        "rejected_venue_patterns": ["Submitted to {conf} {year}", "Withdrawn", "Desk Rejected"],
        "full_name": "International Conference on Machine Learning",
        "conf_name": "ICML",
        "tier": 0,
        "start_year": 2023,  # ICML only available from 2023 on OpenReview
        "conference_month": 7,  # July
    },
    "aaai": {
        # AAAI 2024+ uses OpenReview
        "invitation_pattern_v1": "",
        "accepted_pattern_v1": "",
        "invitation_pattern_v2": "AAAI.org/{year}/Conference/-/Submission",
        "v2_start_year": 2024,
        "accepted_venue_patterns": ["{conf} {year} oral", "{conf} {year} spotlight", "{conf} {year} poster", "{conf} {year}"],
        "rejected_venue_patterns": ["Submitted to {conf} {year}", "Withdrawn", "Desk Rejected"],
        "full_name": "AAAI Conference on Artificial Intelligence",
        "conf_name": "AAAI",
        "tier": 0,
        "start_year": 2024,  # AAAI only available from 2024 on OpenReview
        "conference_month": 2,  # February
    },
}


def _get_content_value(content_field: Any) -> Any:
    """Extract value from content field, handling both v1 and v2 API formats.

    API v1 returns direct values: content["authors"] = ["Author1", "Author2"]
    API v2 returns nested: content["authors"] = {"value": ["Author1", "Author2"]}

    Args:
        content_field: Content field from OpenReview response.

    Returns:
        The actual value (list, string, etc.)
    """
    if isinstance(content_field, dict) and "value" in content_field:
        return content_field.get("value")
    return content_field


class OpenReviewCollector(BaseCrawler):
    """Collector for papers from OpenReview.

    Uses the OpenReview API to collect papers from ML venues
    like ICLR, NeurIPS, and ICML with full metadata including reviews.
    """

    DEFAULT_USER_AGENT = "LexiconArxiv/1.0 (OpenReview Collection)"

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
            checkpoint_name="openreview",
        )

    def _parse_authors(self, note: dict[str, Any]) -> list[Author]:
        """Parse authors from OpenReview note.

        Args:
            note: OpenReview note dictionary.

        Returns:
            List of Author objects.
        """
        authors = []
        content = note.get("content", {})

        # Get author names - handles both v1 (direct list) and v2 (nested dict) formats
        author_names = _get_content_value(content.get("authors", [])) or []
        if not isinstance(author_names, list):
            author_names = []

        # Get authorids if available
        author_ids = _get_content_value(content.get("authorids", [])) or []
        if not isinstance(author_ids, list):
            author_ids = []

        for i, name in enumerate(author_names):
            if isinstance(name, str):
                author = Author(name=name)
                # Add OpenReview profile ID if available
                if author_ids and i < len(author_ids) and author_ids[i]:
                    author_id = author_ids[i]
                    if isinstance(author_id, str) and author_id.startswith("~"):
                        author.openalex_id = None  # Store as profile link
                authors.append(author)

        return authors

    def _determine_paper_type(self, note: dict[str, Any]) -> PaperType:
        """Determine paper type from OpenReview note.

        Args:
            note: OpenReview note dictionary.

        Returns:
            PaperType enum value.
        """
        content = note.get("content", {})

        # Get title - handles both v1 and v2 formats
        title = _get_content_value(content.get("title", "")) or ""
        title = title.lower() if isinstance(title, str) else ""

        # Get keywords - handles both v1 and v2 formats
        keywords_raw = _get_content_value(content.get("keywords", [])) or []
        keywords = [k.lower() for k in keywords_raw if isinstance(k, str)]

        # Check title for type indicators
        if "survey" in title or "review" in title:
            return PaperType.SURVEY
        if "dataset" in title or "benchmark" in title:
            return PaperType.DATASET
        if "demo" in title or "demonstration" in title:
            return PaperType.DEMO
        if "position" in title:
            return PaperType.POSITION
        if "analysis" in title or "empirical study" in title:
            return PaperType.ANALYSIS

        # Check keywords
        if any(k in ["survey", "review", "tutorial"] for k in keywords):
            return PaperType.SURVEY
        if any(k in ["dataset", "benchmark", "corpus"] for k in keywords):
            return PaperType.DATASET

        return PaperType.METHOD

    def _parse_note(
        self,
        note: dict[str, Any],
        venue_name: str,
        venue_info: dict[str, Any],
        year: int,
    ) -> RawPaper | None:
        """Parse an OpenReview note into a RawPaper.

        Args:
            note: OpenReview note dictionary.
            venue_name: Short venue name.
            venue_info: Venue info dictionary from OPENREVIEW_VENUES.
            year: Conference year.

        Returns:
            RawPaper object or None if parsing fails.
        """
        try:
            content = note.get("content", {})

            # Get title - handles both v1 and v2 formats
            title = _get_content_value(content.get("title", ""))
            if not title or not isinstance(title, str):
                return None

            # Get abstract - handles both v1 and v2 formats
            abstract = _get_content_value(content.get("abstract", "")) or ""
            if not isinstance(abstract, str):
                abstract = ""

            # Get authors
            authors = self._parse_authors(note)

            # Get keywords - handles both v1 and v2 formats
            keywords = _get_content_value(content.get("keywords", [])) or []
            if not isinstance(keywords, list):
                keywords = []

            # Get PDF URL - handles both v1 and v2 formats
            pdf_url = _get_content_value(content.get("pdf", ""))
            if pdf_url and isinstance(pdf_url, str) and not pdf_url.startswith("http"):
                pdf_url = f"https://openreview.net{pdf_url}"

            # Get venue/track information - handles both v1 and v2 formats
            venue_str = _get_content_value(content.get("venue", ""))
            venue_text = venue_str if isinstance(venue_str, str) and venue_str else venue_info["full_name"]

            # Get OpenReview forum ID
            forum_id = note.get("forum") or note.get("id", "")

            # Build abstract URL
            abstract_url = f"https://openreview.net/forum?id={forum_id}" if forum_id else None

            # Determine paper type
            paper_type = self._determine_paper_type(note)

            # Get creation date for month
            cdate = note.get("cdate") or note.get("tcdate")
            month = venue_info.get("conference_month")
            if cdate:
                try:
                    dt = datetime.fromtimestamp(cdate / 1000)  # cdate is in milliseconds
                    month = dt.month
                except (ValueError, TypeError, OSError):
                    pass

            return RawPaper(
                source=SourceType.OPENREVIEW,
                source_id=forum_id,
                title=title,
                abstract=abstract,
                authors=authors,
                year=year,
                month=month,
                venue=venue_text,
                venue_type="conference",
                paper_type=paper_type,
                keywords=keywords,
                pdf_url=pdf_url,
                abstract_url=abstract_url,
                tier=venue_info.get("tier", 0),
                is_core=True,
                raw_data=note,
            )

        except Exception as e:
            logger.warning(f"Failed to parse OpenReview note: {e}")
            return None

    def _is_accepted(
        self,
        note: dict[str, Any],
        venue_info: dict[str, Any] | None = None,
        year: int | None = None,
    ) -> bool:
        """Check if a paper was accepted.

        For API v1 (<=2023): Uses decision replies.
        For API v2 (2024+): Uses content.venue field.

        Args:
            note: OpenReview note dictionary.
            venue_info: Venue configuration dict (for v2 pattern matching).
            year: Conference year (to determine API version).

        Returns:
            True if the paper was accepted, False otherwise.
        """
        # API v2: Check content.venue field
        # Each venue has its own v2_start_year when it migrated to API v2
        v2_start_year = venue_info.get("v2_start_year", 2024) if venue_info else 2024
        if year and year >= v2_start_year and venue_info:
            content = note.get("content", {})
            venue_value = _get_content_value(content.get("venue", "")) or ""

            # Check against rejected patterns first
            rejected_patterns = venue_info.get("rejected_venue_patterns", [])
            conf_name = venue_info.get("conf_name", "")
            for pattern in rejected_patterns:
                reject_str = pattern.format(conf=conf_name, year=year)
                if reject_str.lower() in venue_value.lower():
                    return False

            # Check against accepted patterns
            accepted_patterns = venue_info.get("accepted_venue_patterns", [])
            for pattern in accepted_patterns:
                accept_str = pattern.format(conf=conf_name, year=year)
                if accept_str.lower() in venue_value.lower():
                    return True

            # If venue is set but doesn't match accepted patterns, likely rejected
            if venue_value:
                return False
            # No venue set - fall through to v1 check

        # API v1 (<=2023): Check decision replies
        replies = note.get("details", {}).get("directReplies", [])
        for reply in replies:
            invitation = reply.get("invitation", "")
            # Check for decision invitation patterns
            if "Decision" in invitation:
                content = reply.get("content", {})
                # Handle both v1 and v2 API formats
                decision = _get_content_value(content.get("decision", ""))
                if decision and "Accept" in str(decision):
                    return True
            # Also check for acceptance invitation patterns
            if "Accept" in invitation:
                return True
        return False

    async def _fetch_notes(
        self,
        venue: str,
        year: int,
        offset: int = 0,
        accepted_only: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch notes from OpenReview API for a venue/year.

        Uses API v1 for years <= 2023, API v2 for 2024+.

        Args:
            venue: Venue name (key in OPENREVIEW_VENUES).
            year: Conference year.
            offset: Pagination offset.
            accepted_only: If True, request decision details for filtering (v1 only).

        Returns:
            Tuple of (list of notes, total count).
        """
        venue_lower = venue.lower()
        if venue_lower not in OPENREVIEW_VENUES:
            return [], 0

        venue_info = OPENREVIEW_VENUES[venue_lower]

        # Determine API version and invitation pattern based on year
        # Each venue has its own v2_start_year when it migrated to API v2
        v2_start_year = venue_info.get("v2_start_year", 2024)
        use_v2 = year >= v2_start_year
        if use_v2:
            api_url = OPENREVIEW_API_V2
            invitation = venue_info.get("invitation_pattern_v2", "").format(year=year)
        else:
            api_url = OPENREVIEW_API_V1
            invitation = venue_info.get("invitation_pattern_v1", "").format(year=year)

        if not invitation:
            logger.warning(f"No invitation pattern for {venue} {year}")
            return [], 0

        # Build params
        params = {
            "invitation": invitation,
            "limit": OPENREVIEW_PER_PAGE,
            "offset": offset,
        }

        # For v1, request directReplies to get decision info for filtering
        # For v2, filtering is done by content.venue in _is_accepted()
        if accepted_only and not use_v2:
            params["details"] = "directReplies"

        try:
            response = await self.client.get(
                f"{api_url}/notes",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            notes = data.get("notes", [])
            # API v2 doesn't always return count, use notes length as fallback
            total = data.get("count") if data.get("count") is not None else len(notes)

            return notes, total

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Venue/year not found, try alternative invitation patterns
                logger.debug(f"Invitation not found: {invitation}")
                return [], 0
            logger.error(f"OpenReview API error: {e}")
            return [], 0
        except Exception as e:
            logger.error(f"OpenReview fetch failed: {e}")
            return [], 0

    async def _get_venue_years(
        self,
        venue: str,
        since_year: int,
        to_year: int | None,
    ) -> list[int]:
        """Get list of valid years for a venue.

        Args:
            venue: Venue name.
            since_year: Start year.
            to_year: End year (inclusive).

        Returns:
            List of years to collect from.
        """
        venue_lower = venue.lower()
        if venue_lower not in OPENREVIEW_VENUES:
            return []

        venue_info = OPENREVIEW_VENUES[venue_lower]
        start_year = max(since_year, venue_info["start_year"])
        end_year = to_year or datetime.now().year

        return list(range(start_year, end_year + 1))

    async def collect_venue(
        self,
        venue: str,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
        accepted_only: bool = True,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a specific OpenReview venue.

        Args:
            venue: Venue name (e.g., "iclr", "neurips", "icml").
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format.
            to_date: End date in YYYY-MM-DD or YYYY-MM format.
            accepted_only: If True, only collect accepted papers (default).

        Yields:
            Batches of collected papers.
        """
        # Parse date constraints
        if since_date:
            since_year = int(since_date[:4])
        if to_date:
            to_year = int(to_date[:4])

        venue_lower = venue.lower()
        if venue_lower not in OPENREVIEW_VENUES:
            logger.error(f"Unknown OpenReview venue: {venue}")
            return

        venue_info = OPENREVIEW_VENUES[venue_lower]

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = f"openreview_{venue_lower}"

        # Check if already complete
        if self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info(f"Venue {venue} already complete, skipping")
            return

        filter_msg = " (accepted only)" if accepted_only else " (all submissions)"
        logger.info(f"Collecting OpenReview: {venue} from {since_year}{filter_msg}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        # Get years to process
        years = await self._get_venue_years(venue, since_year, to_year)

        try:
            for year in years:
                offset = 0
                year_total = None
                accepted_count = 0
                v2_start_year = venue_info.get("v2_start_year", 2024)
                use_v2 = year >= v2_start_year

                while True:
                    notes, total = await self._fetch_notes(
                        venue, year, offset, accepted_only=accepted_only
                    )

                    if year_total is None:
                        year_total = total
                        api_version = "v2" if use_v2 else "v1"
                        logger.info(
                            f"OpenReview {venue} {year} (API {api_version}): "
                            f"{total if total else 'unknown'} submissions found"
                        )

                    if not notes:
                        break

                    # Parse, filter by acceptance, and deduplicate
                    batch = []
                    for note in notes:
                        # Filter by acceptance decision if requested
                        if accepted_only and not self._is_accepted(note, venue_info, year):
                            continue

                        accepted_count += 1
                        paper = self._parse_note(note, venue_lower, venue_info, year)
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

                    offset += len(notes)

                    # Update checkpoint
                    self.checkpoint_manager.update_venue(
                        checkpoint,
                        checkpoint_key,
                        cursor=f"{year}:{offset}",
                        papers_collected=papers_collected,
                    )

                    # Check if we've collected all papers for this year
                    # For v2 API, year_total might be 0 or unreliable, so also check notes length
                    if year_total and offset >= year_total:
                        break
                    if len(notes) < OPENREVIEW_PER_PAGE:
                        # Got fewer notes than requested, means we've reached the end
                        break

                    # Rate limiting - 1 req/sec for unauthenticated
                    await asyncio.sleep(1.0)

                # Log year summary
                if accepted_only:
                    logger.info(f"OpenReview {venue} {year}: {accepted_count} accepted papers")

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed OpenReview {venue}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting OpenReview {venue}: {e}")
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
        accepted_only: bool = True,
    ) -> int:
        """Collect papers from all OpenReview venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).
            accepted_only: If True, only collect accepted papers (default).

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        logger.info(f"Collecting from {len(OPENREVIEW_VENUES)} OpenReview venues")

        total = 0
        for venue in OPENREVIEW_VENUES:
            async for batch in self.collect_venue(
                venue, since_year, to_year, accepted_only=accepted_only
            ):
                total += len(batch)

        logger.info(f"OpenReview collection complete: {total} papers")
        return total


def get_openreview_venues() -> list[str]:
    """Get list of available OpenReview venues."""
    return list(OPENREVIEW_VENUES.keys())


def get_openreview_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about an OpenReview venue."""
    return OPENREVIEW_VENUES.get(venue.lower())
