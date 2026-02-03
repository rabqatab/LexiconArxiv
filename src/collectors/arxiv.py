"""arXiv API collector for preprints.

arXiv is a free distribution service for scholarly articles.
API docs: https://info.arxiv.org/help/api/
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import feedparser

from src.collectors.base import BaseCollector
from src.models.paper import Author, PaperType, RawPaper, SourceType

logger = logging.getLogger(__name__)


# arXiv categories for AI/NLP
ARXIV_CATEGORIES = {
    "cs.CL": "Computation and Language",
    "cs.AI": "Artificial Intelligence",
    "cs.LG": "Machine Learning",
    "cs.IR": "Information Retrieval",
    "cs.CV": "Computer Vision",
    "cs.NE": "Neural and Evolutionary Computing",
}

# Namespace for arXiv XML
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivCollector(BaseCollector):
    """Collector for arXiv API.

    arXiv provides access to preprints in various scientific fields.
    Rate limit: 3 requests per second.
    """

    SOURCE_TYPE = SourceType.ARXIV
    BASE_URL = "http://export.arxiv.org/api/query"
    DEFAULT_TIMEOUT = 60.0  # arXiv can be slow
    RATE_LIMIT_DELAY = 0.35  # ~3 requests per second

    def __init__(
        self,
        timeout: float | None = None,
        email: str | None = None,
    ):
        """Initialize arXiv collector.

        Args:
            timeout: Request timeout in seconds.
            email: Contact email (included in User-Agent).
        """
        super().__init__(timeout=timeout or self.DEFAULT_TIMEOUT, email=email)
        self._last_request_time = 0.0

    async def _rate_limit(self) -> None:
        """Ensure we don't exceed rate limits."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    async def search(
        self,
        query: str,
        limit: int = 100,
        categories: list[str] | None = None,
        sort_by: str = "relevance",
    ) -> list[RawPaper]:
        """Search for papers on arXiv.

        Args:
            query: Search query string.
            limit: Maximum number of results (max 2000).
            categories: List of arXiv categories to filter (e.g., ['cs.CL', 'cs.AI']).
            sort_by: Sort order ('relevance', 'lastUpdatedDate', 'submittedDate').

        Returns:
            List of papers matching the query.
        """
        papers = []
        start = 0
        max_results = min(limit, 500)  # Fetch in chunks of 500

        # Build query string
        search_query = self._build_query(query, categories)

        while len(papers) < limit:
            await self._rate_limit()

            params = {
                "search_query": search_query,
                "start": start,
                "max_results": min(max_results, limit - len(papers)),
                "sortBy": sort_by,
                "sortOrder": "descending",
            }

            url = f"{self.BASE_URL}?{urlencode(params)}"
            response = await self.get(url)

            # Parse Atom feed
            feed = feedparser.parse(response.text)

            if not feed.entries:
                break

            for entry in feed.entries:
                paper = self._parse_entry(entry)
                if paper:
                    papers.append(paper)

            start += len(feed.entries)

            # Check if we've reached the end
            total_results = int(feed.feed.get("opensearch_totalresults", 0))
            if start >= total_results:
                break

        logger.info(f"arXiv search '{query}': found {len(papers)} papers")
        return papers

    async def search_recent(
        self,
        categories: list[str] | None = None,
        days: int = 7,
        limit: int = 100,
    ) -> list[RawPaper]:
        """Search for recent papers in specified categories.

        Args:
            categories: arXiv categories to search.
            days: Number of days to look back.
            limit: Maximum number of results.

        Returns:
            List of recent papers.
        """
        cats = categories or list(ARXIV_CATEGORIES.keys())
        return await self.search(
            query="",
            categories=cats,
            limit=limit,
            sort_by="submittedDate",
        )

    async def fetch_by_id(self, paper_id: str) -> RawPaper | None:
        """Fetch a paper by arXiv ID.

        Args:
            paper_id: arXiv ID (e.g., '2304.12345' or '2304.12345v2').

        Returns:
            The paper if found, None otherwise.
        """
        # Clean the ID
        paper_id = self._clean_arxiv_id(paper_id)

        await self._rate_limit()

        params = {"id_list": paper_id}
        url = f"{self.BASE_URL}?{urlencode(params)}"

        try:
            response = await self.get(url)
            feed = feedparser.parse(response.text)

            if feed.entries:
                return self._parse_entry(feed.entries[0])
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch arXiv paper {paper_id}: {e}")
            return None

    def _build_query(self, query: str, categories: list[str] | None) -> str:
        """Build arXiv API query string.

        arXiv uses a specific query syntax:
        - all: search all fields
        - ti: title
        - au: author
        - abs: abstract
        - cat: category
        """
        parts = []

        if query:
            # Search in title and abstract
            parts.append(f'all:"{query}"')

        if categories:
            cat_query = " OR ".join(f"cat:{cat}" for cat in categories)
            parts.append(f"({cat_query})")

        if not parts:
            # Default to AI/NLP categories
            default_cats = ["cs.CL", "cs.AI", "cs.LG"]
            cat_query = " OR ".join(f"cat:{cat}" for cat in default_cats)
            parts.append(f"({cat_query})")

        return " AND ".join(parts)

    def _clean_arxiv_id(self, arxiv_id: str) -> str:
        """Clean arXiv ID to standard format."""
        # Remove URL prefix if present
        arxiv_id = arxiv_id.replace("http://arxiv.org/abs/", "")
        arxiv_id = arxiv_id.replace("https://arxiv.org/abs/", "")
        return arxiv_id

    def _extract_arxiv_id(self, entry_id: str) -> str:
        """Extract arXiv ID from entry URL."""
        # Entry ID format: http://arxiv.org/abs/2304.12345v1
        match = re.search(r"arxiv\.org/abs/(.+)$", entry_id)
        if match:
            return match.group(1)
        return entry_id

    def _parse_entry(self, entry: Any) -> RawPaper | None:
        """Parse arXiv Atom feed entry into RawPaper.

        Args:
            entry: feedparser entry object.

        Returns:
            Parsed RawPaper or None if parsing fails.
        """
        try:
            # Extract arXiv ID
            arxiv_id = self._extract_arxiv_id(entry.id)
            # Remove version suffix for base ID
            base_id = re.sub(r"v\d+$", "", arxiv_id)

            # Extract authors
            authors = []
            for author in entry.get("authors", []):
                name = author.get("name", "Unknown")
                affiliation = None
                if hasattr(author, "arxiv_affiliation"):
                    affiliation = author.arxiv_affiliation
                authors.append(Author(name=name, affiliation=affiliation))

            # Extract categories
            categories = []
            primary_category = None
            if hasattr(entry, "arxiv_primary_category"):
                primary_category = entry.arxiv_primary_category.get("term")
                categories.append(primary_category)

            for tag in entry.get("tags", []):
                term = tag.get("term", "")
                if term and term not in categories:
                    categories.append(term)

            # Extract year from published date
            published = entry.get("published", "")
            year = None
            month = None
            published_date = None
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    year = dt.year
                    month = dt.month
                    published_date = dt
                except ValueError:
                    pass

            # Extract DOI if present
            doi = None
            if hasattr(entry, "arxiv_doi"):
                doi = entry.arxiv_doi

            # Get PDF URL
            pdf_url = None
            for link in entry.get("links", []):
                if link.get("type") == "application/pdf":
                    pdf_url = link.get("href")
                    break
            if not pdf_url:
                pdf_url = f"https://arxiv.org/pdf/{base_id}"

            # Clean abstract
            abstract = entry.get("summary", "")
            if abstract:
                abstract = re.sub(r"\s+", " ", abstract).strip()

            return RawPaper(
                source=SourceType.ARXIV,
                source_id=base_id,
                title=entry.get("title", "").replace("\n", " ").strip(),
                abstract=abstract,
                authors=authors,
                year=year,
                month=month,
                doi=doi,
                arxiv_id=base_id,
                venue="arXiv",
                venue_type="preprint",
                paper_type=PaperType.METHOD,  # Default for preprints
                categories=categories,
                pdf_url=pdf_url,
                abstract_url=f"https://arxiv.org/abs/{base_id}",
                published_date=published_date,
                raw_data=dict(entry),
            )

        except Exception as e:
            logger.warning(f"Failed to parse arXiv entry: {e}")
            return None

    def get_source_name(self) -> str:
        return "arXiv"
