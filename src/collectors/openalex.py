"""OpenAlex API collector for academic papers.

OpenAlex is a free, open catalog of the world's scholarly works.
API docs: https://docs.openalex.org/
"""

import logging
from typing import Any
from urllib.parse import urlencode

from src.collectors.base import BaseCollector
from src.models.paper import Author, PaperType, RawPaper, SourceType

logger = logging.getLogger(__name__)


# AI/NLP related concept IDs in OpenAlex
CONCEPT_IDS = {
    "artificial_intelligence": "C41008148",
    "natural_language_processing": "C204321447",
    "machine_learning": "C119857082",
    "deep_learning": "C108583219",
    "information_retrieval": "C17744445",
}


class OpenAlexCollector(BaseCollector):
    """Collector for OpenAlex API.

    OpenAlex provides free access to scholarly metadata including papers,
    authors, venues, and citations.
    """

    SOURCE_TYPE = SourceType.OPENALEX
    BASE_URL = "https://api.openalex.org"
    DEFAULT_PER_PAGE = 200  # Max allowed by OpenAlex

    def __init__(
        self,
        email: str | None = None,
        timeout: float | None = None,
    ):
        """Initialize OpenAlex collector.

        Args:
            email: Contact email for polite pool access (higher rate limits).
            timeout: Request timeout in seconds.
        """
        super().__init__(timeout=timeout, email=email)

    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build API URL with parameters."""
        if self.email:
            params["mailto"] = self.email
        query_string = urlencode(params, doseq=True)
        return f"{self.BASE_URL}/{endpoint}?{query_string}"

    async def search(
        self,
        query: str,
        limit: int = 100,
        year_from: int | None = None,
        year_to: int | None = None,
        concepts: list[str] | None = None,
    ) -> list[RawPaper]:
        """Search for papers in OpenAlex.

        Args:
            query: Search query string.
            limit: Maximum number of results (max 10000 per query).
            year_from: Filter papers from this year.
            year_to: Filter papers until this year.
            concepts: List of OpenAlex concept IDs to filter by.

        Returns:
            List of papers matching the query.
        """
        papers = []
        cursor = "*"
        per_page = min(limit, self.DEFAULT_PER_PAGE)

        # Build filter string
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if concepts:
            filters.append(f"concepts.id:{"|".join(concepts)}")

        while len(papers) < limit:
            params = {
                "search": query,
                "per-page": per_page,
                "cursor": cursor,
            }
            if filters:
                params["filter"] = ",".join(filters)

            url = self._build_url("works", params)
            response = await self.get(url)
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            for work in results:
                paper = self._parse_work(work)
                if paper:
                    papers.append(paper)
                    if len(papers) >= limit:
                        break

            # Get next cursor for pagination
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break

        logger.info(f"OpenAlex search '{query}': found {len(papers)} papers")
        return papers

    async def search_ai_nlp(
        self,
        query: str,
        limit: int = 100,
        year_from: int | None = 2018,
    ) -> list[RawPaper]:
        """Search specifically for AI/NLP papers.

        Args:
            query: Search query string.
            limit: Maximum number of results.
            year_from: Filter papers from this year (default: 2018).

        Returns:
            List of AI/NLP papers matching the query.
        """
        concepts = [
            CONCEPT_IDS["artificial_intelligence"],
            CONCEPT_IDS["natural_language_processing"],
            CONCEPT_IDS["machine_learning"],
        ]
        return await self.search(
            query=query,
            limit=limit,
            year_from=year_from,
            concepts=concepts,
        )

    async def fetch_by_id(self, paper_id: str) -> RawPaper | None:
        """Fetch a paper by OpenAlex ID.

        Args:
            paper_id: OpenAlex work ID (e.g., 'W2741809807').

        Returns:
            The paper if found, None otherwise.
        """
        # Ensure proper format
        if not paper_id.startswith("W"):
            paper_id = f"W{paper_id}"

        url = f"{self.BASE_URL}/works/{paper_id}"
        if self.email:
            url += f"?mailto={self.email}"

        try:
            response = await self.get(url)
            data = response.json()
            return self._parse_work(data)
        except Exception as e:
            logger.warning(f"Failed to fetch paper {paper_id}: {e}")
            return None

    async def fetch_by_doi(self, doi: str) -> RawPaper | None:
        """Fetch a paper by DOI.

        Args:
            doi: The DOI (e.g., '10.1234/example').

        Returns:
            The paper if found, None otherwise.
        """
        url = f"{self.BASE_URL}/works/https://doi.org/{doi}"
        if self.email:
            url += f"?mailto={self.email}"

        try:
            response = await self.get(url)
            data = response.json()
            return self._parse_work(data)
        except Exception as e:
            logger.warning(f"Failed to fetch paper by DOI {doi}: {e}")
            return None

    def _parse_work(self, work: dict[str, Any]) -> RawPaper | None:
        """Parse OpenAlex work object into RawPaper.

        Args:
            work: OpenAlex work dictionary.

        Returns:
            Parsed RawPaper or None if parsing fails.
        """
        try:
            # Extract basic info
            openalex_id = work.get("id", "").replace("https://openalex.org/", "")
            title = work.get("title") or work.get("display_name", "")

            if not title:
                return None

            # Extract authors
            authors = []
            for authorship in work.get("authorships", []):
                author_data = authorship.get("author", {})
                institutions = authorship.get("institutions", [])

                author = Author(
                    name=author_data.get("display_name", "Unknown"),
                    openalex_id=author_data.get("id", "").replace(
                        "https://openalex.org/", ""
                    ),
                    orcid=author_data.get("orcid"),
                    affiliation=institutions[0].get("display_name") if institutions else None,
                )
                authors.append(author)

            # Extract venue
            primary_location = work.get("primary_location") or {}
            source = primary_location.get("source") or {}
            venue = source.get("display_name")
            venue_type = source.get("type")

            # Extract DOI
            doi = work.get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")

            # Reconstruct abstract from inverted index
            abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

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
                venue=venue,
                venue_type=venue_type,
                paper_type=paper_type,
                categories=categories,
                citation_count=work.get("cited_by_count", 0),
                pdf_url=primary_location.get("pdf_url"),
                abstract_url=work.get("id"),
                raw_data=work,
            )

        except Exception as e:
            logger.warning(f"Failed to parse work: {e}")
            return None

    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index format.

        OpenAlex stores abstracts as inverted indexes to save space.
        Format: {"word": [position1, position2, ...], ...}
        """
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
        """Map OpenAlex work type to our PaperType enum."""
        type_mapping = {
            "article": PaperType.METHOD,
            "review": PaperType.SURVEY,
            "preprint": PaperType.METHOD,
            "dataset": PaperType.DATASET,
            "book-chapter": PaperType.OTHER,
        }
        return type_mapping.get(work_type or "", PaperType.OTHER)

    def get_source_name(self) -> str:
        return "OpenAlex"
