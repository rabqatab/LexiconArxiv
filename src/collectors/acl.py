"""ACL Anthology collector for NLP papers.

ACL Anthology is the official collection of papers from ACL conferences.
Data source: https://aclanthology.org/
"""

import logging
import re
from typing import Any
from urllib.parse import urlencode

from src.collectors.base import BaseCollector
from src.models.paper import Author, PaperType, RawPaper, SourceType

logger = logging.getLogger(__name__)


# ACL venue mappings
ACL_VENUES = {
    "P": "ACL",
    "N": "NAACL",
    "D": "EMNLP",
    "E": "EACL",
    "W": "Workshop",
    "C": "COLING",
    "L": "LREC",
    "Q": "TACL",
    "J": "CL Journal",
    "K": "CoNLL",
    "S": "SemEval",
    "I": "IJCNLP",
}

# ACL Anthology API base URL (using Semantic Scholar as proxy for search)
# Note: ACL Anthology doesn't have a native search API, so we use alternative approaches
ACL_ANTHOLOGY_URL = "https://aclanthology.org"


class ACLAnthologyCollector(BaseCollector):
    """Collector for ACL Anthology papers.

    ACL Anthology contains papers from major NLP/CL conferences and journals.
    Since ACL Anthology doesn't have a native search API, we use:
    1. Semantic Scholar API with venue filter for search
    2. Direct ACL Anthology access for fetching by ID
    """

    SOURCE_TYPE = SourceType.ACL
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    DEFAULT_TIMEOUT = 30.0

    # ACL-related venues for Semantic Scholar search
    ACL_VENUE_IDS = [
        "ACL",
        "NAACL",
        "EMNLP",
        "EACL",
        "COLING",
        "CoNLL",
        "TACL",
        "Computational Linguistics",
    ]

    def __init__(
        self,
        timeout: float | None = None,
        email: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize ACL Anthology collector.

        Args:
            timeout: Request timeout in seconds.
            email: Contact email.
            api_key: Semantic Scholar API key (optional, for higher rate limits).
        """
        super().__init__(timeout=timeout, email=email)
        self.api_key = api_key

    def _get_headers(self) -> dict[str, str]:
        """Get headers including API key if available."""
        headers = super()._get_headers()
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def search(
        self,
        query: str,
        limit: int = 100,
        year_from: int | None = None,
        year_to: int | None = None,
        venues: list[str] | None = None,
    ) -> list[RawPaper]:
        """Search for ACL papers using Semantic Scholar API.

        Args:
            query: Search query string.
            limit: Maximum number of results.
            year_from: Filter papers from this year.
            year_to: Filter papers until this year.
            venues: Specific ACL venues to search (default: all ACL venues).

        Returns:
            List of papers matching the query.
        """
        papers = []
        offset = 0
        per_page = min(limit, 100)  # S2 max is 100

        target_venues = venues or self.ACL_VENUE_IDS

        while len(papers) < limit:
            params = {
                "query": query,
                "offset": offset,
                "limit": per_page,
                "fields": "paperId,title,abstract,authors,year,venue,publicationDate,"
                "externalIds,url,citationCount,publicationTypes",
            }

            # Add year filter
            if year_from or year_to:
                year_filter = ""
                if year_from:
                    year_filter = f"{year_from}-"
                if year_to:
                    year_filter += str(year_to)
                elif year_from:
                    year_filter += "2030"  # Far future
                params["year"] = year_filter

            url = f"{self.BASE_URL}/paper/search"
            response = await self.get(url, params=params)
            data = response.json()

            results = data.get("data", [])
            if not results:
                break

            for paper_data in results:
                # Filter by ACL venues
                venue = paper_data.get("venue", "")
                if not self._is_acl_venue(venue, target_venues):
                    continue

                paper = self._parse_s2_paper(paper_data)
                if paper:
                    papers.append(paper)
                    if len(papers) >= limit:
                        break

            offset += len(results)

            # Check if more results available
            total = data.get("total", 0)
            if offset >= total:
                break

        logger.info(f"ACL search '{query}': found {len(papers)} papers")
        return papers

    async def fetch_by_id(self, paper_id: str) -> RawPaper | None:
        """Fetch a paper by ACL Anthology ID.

        Args:
            paper_id: ACL Anthology ID (e.g., '2023.acl-long.1' or 'P19-1001').

        Returns:
            The paper if found, None otherwise.
        """
        # Try to fetch via Semantic Scholar using ACL ID
        params = {
            "fields": "paperId,title,abstract,authors,year,venue,publicationDate,"
            "externalIds,url,citationCount,publicationTypes",
        }

        url = f"{self.BASE_URL}/paper/ACL:{paper_id}"

        try:
            response = await self.get(url, params=params)
            data = response.json()
            return self._parse_s2_paper(data)
        except Exception as e:
            logger.warning(f"Failed to fetch ACL paper {paper_id}: {e}")
            return None

    async def fetch_by_s2_id(self, s2_id: str) -> RawPaper | None:
        """Fetch a paper by Semantic Scholar ID.

        Args:
            s2_id: Semantic Scholar paper ID.

        Returns:
            The paper if found, None otherwise.
        """
        params = {
            "fields": "paperId,title,abstract,authors,year,venue,publicationDate,"
            "externalIds,url,citationCount,publicationTypes",
        }

        url = f"{self.BASE_URL}/paper/{s2_id}"

        try:
            response = await self.get(url, params=params)
            data = response.json()
            return self._parse_s2_paper(data)
        except Exception as e:
            logger.warning(f"Failed to fetch paper {s2_id}: {e}")
            return None

    def _is_acl_venue(self, venue: str, target_venues: list[str]) -> bool:
        """Check if venue is an ACL venue."""
        if not venue:
            return False

        venue_lower = venue.lower()
        for target in target_venues:
            if target.lower() in venue_lower:
                return True
        return False

    def _extract_acl_id(self, external_ids: dict[str, Any]) -> str | None:
        """Extract ACL Anthology ID from external IDs."""
        acl_id = external_ids.get("ACL")
        if acl_id:
            return acl_id

        # Try to extract from URL or other IDs
        # ACL IDs look like: 2023.acl-long.1, P19-1001, etc.
        return None

    def _map_venue_to_type(self, venue: str) -> str:
        """Map venue name to venue type."""
        venue_lower = venue.lower()
        if any(ws in venue_lower for ws in ["workshop", "semeval", "shared task"]):
            return "workshop"
        if any(jrnl in venue_lower for jrnl in ["journal", "tacl", "computational linguistics"]):
            return "journal"
        return "conference"

    def _parse_s2_paper(self, data: dict[str, Any]) -> RawPaper | None:
        """Parse Semantic Scholar paper data into RawPaper.

        Args:
            data: Semantic Scholar paper dictionary.

        Returns:
            Parsed RawPaper or None if parsing fails.
        """
        try:
            s2_id = data.get("paperId", "")
            title = data.get("title", "")

            if not title:
                return None

            # Extract external IDs
            external_ids = data.get("externalIds", {})
            doi = external_ids.get("DOI")
            arxiv_id = external_ids.get("ArXiv")
            acl_id = self._extract_acl_id(external_ids)

            # Use ACL ID as source_id if available, otherwise S2 ID
            source_id = acl_id or s2_id

            # Extract authors
            authors = []
            for author_data in data.get("authors", []):
                author = Author(
                    name=author_data.get("name", "Unknown"),
                )
                authors.append(author)

            # Extract venue info
            venue = data.get("venue", "")
            venue_type = self._map_venue_to_type(venue)

            # Determine paper type
            pub_types = data.get("publicationTypes", [])
            paper_type = self._map_paper_type(pub_types)

            # Build URLs
            abstract_url = data.get("url")
            pdf_url = None
            if acl_id:
                pdf_url = f"https://aclanthology.org/{acl_id}.pdf"
                abstract_url = f"https://aclanthology.org/{acl_id}"

            return RawPaper(
                source=SourceType.ACL,
                source_id=source_id,
                title=title,
                abstract=data.get("abstract"),
                authors=authors,
                year=data.get("year"),
                doi=doi,
                arxiv_id=arxiv_id,
                acl_id=acl_id,
                venue=venue,
                venue_type=venue_type,
                paper_type=paper_type,
                citation_count=data.get("citationCount", 0),
                pdf_url=pdf_url,
                abstract_url=abstract_url,
                raw_data=data,
            )

        except Exception as e:
            logger.warning(f"Failed to parse S2 paper: {e}")
            return None

    def _map_paper_type(self, pub_types: list[str]) -> PaperType:
        """Map publication types to PaperType."""
        if not pub_types:
            return PaperType.OTHER

        type_lower = [t.lower() for t in pub_types]

        if "review" in type_lower or "survey" in type_lower:
            return PaperType.SURVEY
        if "dataset" in type_lower:
            return PaperType.DATASET

        return PaperType.METHOD

    def get_source_name(self) -> str:
        return "ACL Anthology"
