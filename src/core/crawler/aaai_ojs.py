"""AAAI OJS Crawler for AAAI conference paper collection.

Collects papers from AAAI Open Journal Systems (ojs.aaai.org).
Scrapes the OJS proceedings pages to extract paper metadata.

Note: AAAI 2024+ uses OpenReview, which is handled by the OpenReview collector.
This collector focuses on AAAI proceedings from 2020-2023.
"""

import asyncio
import logging
import re
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.core.checkpoint import CheckpointManager
from src.core.deduplication import Deduplicator
from src.core.storage import QdrantStorage
from src.models.paper import Author, PaperType, RawPaper, SourceType

logger = logging.getLogger(__name__)

# AAAI OJS base URL
AAAI_OJS_BASE_URL = "https://ojs.aaai.org"

# AAAI venue configurations
AAAI_VENUES = {
    "aaai": {
        "archive_url": "https://ojs.aaai.org/index.php/AAAI/issue/archive",
        "issue_pattern": r"AAAI-(\d{2})",  # AAAI-20, AAAI-21, etc.
        "full_name": "AAAI Conference on Artificial Intelligence",
        "tier": 0,
        "conference_month": 2,  # February
    },
    "icwsm": {
        "archive_url": "https://ojs.aaai.org/index.php/ICWSM/issue/archive",
        "issue_pattern": r"ICWSM.*?(\d{4})",
        "full_name": "International AAAI Conference on Web and Social Media",
        "tier": 1,
        "conference_month": 6,  # June
    },
}


class AAOJSCollector:
    """Collector for papers from AAAI OJS platform.

    Scrapes the AAAI proceedings from ojs.aaai.org to extract
    paper metadata including abstracts, authors, and DOIs.
    """

    def __init__(
        self,
        storage: QdrantStorage | None = None,
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
        self.storage = storage or QdrantStorage()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(
            checkpoint_name="aaai_ojs"
        )
        self.timeout = timeout
        self.deduplicator = deduplicator or Deduplicator()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AAOJSCollector":
        """Async context manager entry."""
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

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        if self._client is None:
            raise RuntimeError(
                "Collector must be used as async context manager: "
                "async with AAOJSCollector() as collector: ..."
            )
        return self._client

    def _extract_year_from_issue(self, issue_title: str, pattern: str) -> int | None:
        """Extract year from issue title.

        Args:
            issue_title: The issue title string.
            pattern: Regex pattern to extract year.

        Returns:
            Full year (e.g., 2020) or None.
        """
        match = re.search(pattern, issue_title)
        if match:
            year_str = match.group(1)
            if len(year_str) == 2:
                # Convert 2-digit year to 4-digit
                year_int = int(year_str)
                return 2000 + year_int if year_int < 50 else 1900 + year_int
            return int(year_str)
        return None

    async def _list_issues(
        self,
        venue: str,
        since_year: int,
        to_year: int | None,
    ) -> list[dict[str, Any]]:
        """List available issues for a venue.

        Args:
            venue: Venue name (key in AAAI_VENUES).
            since_year: Start year.
            to_year: End year (inclusive).

        Returns:
            List of issue dictionaries with url, title, year.
        """
        venue_lower = venue.lower()
        if venue_lower not in AAAI_VENUES:
            return []

        venue_info = AAAI_VENUES[venue_lower]
        archive_url = venue_info["archive_url"]
        pattern = venue_info["issue_pattern"]

        try:
            response = await self.client.get(archive_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            issues = []

            # Find issue links in the archive
            for link in soup.select("a.title, h2.title a, .obj_issue_summary a"):
                href = link.get("href")
                title = link.get_text(strip=True)

                if not href or not title:
                    continue

                year = self._extract_year_from_issue(title, pattern)
                if year is None:
                    continue

                # Filter by year range
                if year < since_year:
                    continue
                if to_year and year > to_year:
                    continue

                # Skip AAAI 2024+ (uses OpenReview)
                if venue_lower == "aaai" and year >= 2024:
                    continue

                full_url = urljoin(archive_url, href)
                issues.append({
                    "url": full_url,
                    "title": title,
                    "year": year,
                })

            # Sort by year
            issues.sort(key=lambda x: x["year"])

            return issues

        except Exception as e:
            logger.error(f"Failed to list issues for {venue}: {e}")
            return []

    async def _fetch_issue_papers(
        self,
        issue_url: str,
        year: int,
        venue_info: dict[str, Any],
    ) -> list[RawPaper]:
        """Fetch papers from a single issue.

        Args:
            issue_url: URL of the issue page.
            year: Publication year.
            venue_info: Venue info dictionary.

        Returns:
            List of RawPaper objects.
        """
        papers = []

        try:
            response = await self.client.get(issue_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Find all paper entries
            for article in soup.select(".obj_article_summary, .article_summary"):
                paper = await self._parse_article_summary(
                    article, issue_url, year, venue_info
                )
                if paper:
                    papers.append(paper)

            # Also try table of contents format
            if not papers:
                for toc_entry in soup.select(".tocTitle a, .title a"):
                    href = toc_entry.get("href")
                    if href and "/article/view/" in href:
                        paper = await self._fetch_paper_details(
                            urljoin(issue_url, href), year, venue_info
                        )
                        if paper:
                            papers.append(paper)
                        await asyncio.sleep(1.0)  # Rate limit

        except Exception as e:
            logger.error(f"Failed to fetch issue {issue_url}: {e}")

        return papers

    async def _parse_article_summary(
        self,
        article: Any,
        base_url: str,
        year: int,
        venue_info: dict[str, Any],
    ) -> RawPaper | None:
        """Parse an article summary element.

        Args:
            article: BeautifulSoup element for article summary.
            base_url: Base URL for resolving relative links.
            year: Publication year.
            venue_info: Venue info dictionary.

        Returns:
            RawPaper object or None.
        """
        try:
            # Get title and link
            title_elem = article.select_one(".title a, h3.title a, .article_title a")
            if not title_elem:
                return None

            title = title_elem.get_text(strip=True)
            href = title_elem.get("href")

            if not title or not href:
                return None

            paper_url = urljoin(base_url, href)

            # Fetch full paper details
            return await self._fetch_paper_details(paper_url, year, venue_info)

        except Exception as e:
            logger.debug(f"Failed to parse article summary: {e}")
            return None

    async def _fetch_paper_details(
        self,
        paper_url: str,
        year: int,
        venue_info: dict[str, Any],
    ) -> RawPaper | None:
        """Fetch detailed paper information from paper page.

        Args:
            paper_url: URL of the paper page.
            year: Publication year.
            venue_info: Venue info dictionary.

        Returns:
            RawPaper object or None.
        """
        try:
            response = await self.client.get(paper_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Get title
            title_elem = soup.select_one("h1.page_title, .article_title, meta[name='DC.Title']")
            if title_elem:
                if title_elem.name == "meta":
                    title = title_elem.get("content", "")
                else:
                    title = title_elem.get_text(strip=True)
            else:
                return None

            if not title:
                return None

            # Get abstract
            abstract = None
            abstract_elem = soup.select_one(
                ".abstract p, .article_abstract p, "
                "section.abstract p, meta[name='DC.Description']"
            )
            if abstract_elem:
                if abstract_elem.name == "meta":
                    abstract = abstract_elem.get("content", "")
                else:
                    abstract = abstract_elem.get_text(strip=True)

            # Get authors
            authors = []
            author_elems = soup.select(
                ".authors .name, .article_authors .author, "
                "meta[name='DC.Creator']"
            )
            for author_elem in author_elems:
                if author_elem.name == "meta":
                    name = author_elem.get("content", "")
                else:
                    name = author_elem.get_text(strip=True)
                if name:
                    authors.append(Author(name=name))

            # Get DOI
            doi = None
            doi_elem = soup.select_one(
                ".doi a, a[href*='doi.org'], meta[name='DC.Identifier.DOI']"
            )
            if doi_elem:
                if doi_elem.name == "meta":
                    doi = doi_elem.get("content", "")
                else:
                    doi_href = doi_elem.get("href", "")
                    if "doi.org/" in doi_href:
                        doi = doi_href.split("doi.org/")[-1]

            # Get PDF URL
            pdf_url = None
            pdf_elem = soup.select_one(
                "a.pdf, a[href$='.pdf'], .galley_link a"
            )
            if pdf_elem:
                pdf_href = pdf_elem.get("href")
                if pdf_href:
                    pdf_url = urljoin(paper_url, pdf_href)

            # Get keywords
            keywords = []
            keyword_elems = soup.select(
                ".keywords .keyword, meta[name='keywords']"
            )
            for kw_elem in keyword_elems:
                if kw_elem.name == "meta":
                    kw_content = kw_elem.get("content", "")
                    keywords.extend([k.strip() for k in kw_content.split(",")])
                else:
                    keywords.append(kw_elem.get_text(strip=True))

            # Determine paper type
            paper_type = self._determine_paper_type(title, keywords)

            # Extract source ID from URL
            source_id = paper_url.split("/view/")[-1].split("/")[0] if "/view/" in paper_url else paper_url

            return RawPaper(
                source=SourceType.AAAI,
                source_id=f"aaai-{source_id}",
                title=title,
                abstract=abstract,
                authors=authors,
                year=year,
                month=venue_info.get("conference_month"),
                doi=doi,
                venue=venue_info["full_name"],
                venue_type="conference",
                paper_type=paper_type,
                keywords=keywords,
                pdf_url=pdf_url,
                abstract_url=paper_url,
                tier=venue_info.get("tier", 0),
                is_core=True,
                raw_data={"url": paper_url},
            )

        except Exception as e:
            logger.debug(f"Failed to fetch paper details from {paper_url}: {e}")
            return None

    def _determine_paper_type(self, title: str, keywords: list[str]) -> PaperType:
        """Determine paper type from title and keywords.

        Args:
            title: Paper title.
            keywords: List of keywords.

        Returns:
            PaperType enum value.
        """
        title_lower = title.lower()
        keywords_lower = [k.lower() for k in keywords]

        if "survey" in title_lower or "review" in title_lower:
            return PaperType.SURVEY
        if "dataset" in title_lower or "benchmark" in title_lower:
            return PaperType.DATASET
        if "demo" in title_lower or "demonstration" in title_lower:
            return PaperType.DEMO
        if "position" in title_lower:
            return PaperType.POSITION
        if "analysis" in title_lower or "empirical study" in title_lower:
            return PaperType.ANALYSIS

        if any(k in ["survey", "review"] for k in keywords_lower):
            return PaperType.SURVEY
        if any(k in ["dataset", "benchmark", "corpus"] for k in keywords_lower):
            return PaperType.DATASET

        return PaperType.METHOD

    async def collect_venue(
        self,
        venue: str,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a specific AAAI OJS venue.

        Args:
            venue: Venue name (e.g., "aaai", "icwsm").
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
        if venue_lower not in AAAI_VENUES:
            logger.error(f"Unknown AAAI venue: {venue}")
            return

        venue_info = AAAI_VENUES[venue_lower]

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = f"aaai_{venue_lower}"

        # Check if already complete
        if self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info(f"Venue {venue} already complete, skipping")
            return

        logger.info(f"Collecting AAAI OJS: {venue} from {since_year}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        try:
            # List available issues
            issues = await self._list_issues(venue, since_year, to_year)
            logger.info(f"Found {len(issues)} issues for {venue}")

            for issue in issues:
                issue_url = issue["url"]
                issue_year = issue["year"]
                issue_title = issue["title"]

                logger.info(f"Processing {issue_title} ({issue_year})")

                # Fetch papers from this issue
                papers = await self._fetch_issue_papers(
                    issue_url, issue_year, venue_info
                )

                # Deduplicate and batch
                batch = []
                for paper in papers:
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
                self.checkpoint_manager.update_venue(
                    checkpoint,
                    checkpoint_key,
                    cursor=f"{issue_year}",
                    papers_collected=papers_collected,
                )

                # Rate limiting
                await asyncio.sleep(1.0)

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed AAAI OJS {venue}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting AAAI OJS {venue}: {e}")
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
        """Collect papers from all AAAI OJS venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        logger.info(f"Collecting from {len(AAAI_VENUES)} AAAI OJS venues")

        total = 0
        for venue in AAAI_VENUES:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)

        logger.info(f"AAAI OJS collection complete: {total} papers")
        return total


def get_aaai_venues() -> list[str]:
    """Get list of available AAAI OJS venues."""
    return list(AAAI_VENUES.keys())


def get_aaai_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about an AAAI OJS venue."""
    return AAAI_VENUES.get(venue.lower())
