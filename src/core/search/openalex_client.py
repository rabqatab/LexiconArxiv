"""Async OpenAlex works search client."""

import logging

import httpx

from src.core.constants import (
    OPENALEX_BASE_URL,
    get_openalex_api_keys,
    get_openalex_email,
)

logger = logging.getLogger(__name__)


class OpenAlexSearchClient:
    """Search OpenAlex works endpoint."""

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OpenAlexSearchClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Search OpenAlex works and return normalized results."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        params = {
            "search": query,
            "per_page": max_results,
            "select": "id,title,authorships,doi,publication_year,primary_location,cited_by_count,abstract_inverted_index",
        }

        # Add API key or email for polite pool
        keys = get_openalex_api_keys()
        if keys:
            params["api_key"] = keys[0]
        else:
            email = get_openalex_email()
            if email:
                params["mailto"] = email

        try:
            response = await self._client.get(
                f"{OPENALEX_BASE_URL}/works",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return [self._normalize_work(w) for w in data.get("results", [])]
        except Exception as e:
            logger.error(f"OpenAlex search failed: {e}")
            return []

    def _normalize_work(self, work: dict) -> dict:
        """Normalize an OpenAlex work to the common paper schema."""
        doi = work.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        authors = []
        for authorship in work.get("authorships", [])[:10]:
            author = authorship.get("author", {})
            name = author.get("display_name", "")
            if name:
                authors.append(name)

        venue = None
        location = work.get("primary_location", {}) or {}
        source = location.get("source", {}) or {}
        if source:
            venue = source.get("display_name")

        # Reconstruct abstract from inverted index
        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

        openalex_id = work.get("id", "")
        url = openalex_id if openalex_id.startswith("http") else None

        return {
            "title": work.get("title", ""),
            "abstract": abstract,
            "authors": authors,
            "arxiv_id": None,
            "doi": doi or None,
            "year": work.get("publication_year"),
            "venue": venue,
            "url": url,
            "pdf_url": None,
            "source": "openalex",
        }

    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct abstract text from OpenAlex inverted index format."""
        if not inverted_index:
            return None
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(word for _, word in word_positions) if word_positions else None
