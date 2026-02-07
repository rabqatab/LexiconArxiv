"""Base classes and mixins for enrichment modules.

Provides shared functionality for API fetching, rate limiting, and async context management.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from typing import TYPE_CHECKING, Any

import httpx

from src.core.constants import (
    CROSSREF_BASE_URL,
    OPENALEX_BASE_URL,
    get_crossref_email,
    get_openalex_api_key,
    get_openalex_email,
)

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


class BaseEnricher(ABC):
    """Abstract base class for all enrichers.

    Provides:
    - Async context management
    - httpx client with rate limiting
    - Storage instance
    - Common configuration
    """

    DEFAULT_DELAY = 0.1
    DEFAULT_CONCURRENT = 5

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        delay: float | None = None,
        max_concurrent: int | None = None,
        timeout: float = 30.0,
    ):
        """Initialize BaseEnricher.

        Args:
            storage: QdrantStorage instance. Created if not provided.
            delay: Delay between API calls in seconds.
            max_concurrent: Maximum concurrent API requests.
            timeout: HTTP client timeout in seconds.
        """
        from src.core.storage import QdrantStorage

        self.storage = storage or QdrantStorage()
        self.delay = delay if delay is not None else self.DEFAULT_DELAY
        self.max_concurrent = (
            max_concurrent if max_concurrent is not None else self.DEFAULT_CONCURRENT
        )
        self.timeout = timeout

        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "BaseEnricher":
        """Enter async context."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _rate_limited_request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a rate-limited HTTP request.

        Args:
            method: HTTP method (get, post, etc.)
            url: URL to request
            **kwargs: Additional arguments passed to httpx

        Returns:
            httpx.Response
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        async with self._semaphore:
            response = await getattr(self._client, method)(url, **kwargs)
            await asyncio.sleep(self.delay)
            return response


class OpenAlexMixin:
    """Mixin providing OpenAlex API fetching functionality.

    Requires the class to have:
    - _client: httpx.AsyncClient
    - _semaphore: asyncio.Semaphore
    - delay: float
    """

    # These will be set by __init__ in subclasses
    email: str | None = None
    api_key: str | None = None
    _api_key_exhausted: bool = False  # Track if API key credits are exhausted
    _client: httpx.AsyncClient | None = None
    _semaphore: asyncio.Semaphore | None = None
    delay: float = 0.1

    def _init_openalex(
        self,
        email: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize OpenAlex credentials.

        Args:
            email: Email for polite pool. Uses OPENALEX_EMAIL env if not set.
            api_key: OpenAlex API key. Uses OPENALEX_API_KEY env if not set.
        """
        self.email = email or get_openalex_email()
        self.api_key = api_key or get_openalex_api_key()
        self._api_key_exhausted = False

    def _get_openalex_params(self) -> dict[str, str]:
        """Get query parameters for OpenAlex API calls.

        Falls back to email-based polite pool if API key credits are exhausted.
        """
        params = {}
        # Use API key only if available AND not exhausted
        if self.api_key and not self._api_key_exhausted:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email
        return params

    def _handle_api_key_exhaustion(self, response: "httpx.Response") -> bool:
        """Check if response indicates API key credit exhaustion.

        Args:
            response: HTTP response to check.

        Returns:
            True if credits exhausted and switched to email, False otherwise.
        """
        if response.status_code == 429 and self.api_key and not self._api_key_exhausted:
            try:
                data = response.json()
                if "Insufficient credits" in data.get("message", ""):
                    self._api_key_exhausted = True
                    logger.warning(
                        "OpenAlex API key credits exhausted. "
                        "Falling back to email-based polite pool."
                    )
                    return True
            except Exception:
                pass
        return False

    def has_valid_api_key(self) -> bool:
        """Check if a valid (non-exhausted) API key is available."""
        return bool(self.api_key and not self._api_key_exhausted)

    async def fetch_openalex_work(
        self,
        identifier: str,
        identifier_type: str = "doi",
    ) -> dict[str, Any] | None:
        """Fetch paper metadata from OpenAlex.

        Args:
            identifier: The identifier value.
            identifier_type: Type of identifier ('doi', 'arxiv', 'openalex').

        Returns:
            Metadata dict or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Build URL based on identifier type
        if identifier_type == "doi":
            url = f"{OPENALEX_BASE_URL}/works/https://doi.org/{identifier}"
        elif identifier_type == "arxiv":
            url = f"{OPENALEX_BASE_URL}/works/arXiv:{identifier}"
        elif identifier_type == "openalex":
            work_id = identifier if identifier.startswith("W") else f"W{identifier}"
            url = f"{OPENALEX_BASE_URL}/works/{work_id}"
        else:
            raise ValueError(f"Unknown identifier type: {identifier_type}")

        params = self._get_openalex_params()

        try:
            async with self._semaphore:
                response = await self._client.get(url, params=params)
                await asyncio.sleep(self.delay)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                # Check if API key credits exhausted - if so, switch to email and retry
                if self._handle_api_key_exhaustion(response):
                    return await self.fetch_openalex_work(identifier, identifier_type)
                # Regular rate limiting - wait and retry
                logger.warning("Rate limited by OpenAlex, waiting 60s...")
                await asyncio.sleep(60)
                return await self.fetch_openalex_work(identifier, identifier_type)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.debug(f"OpenAlex HTTP error: {e}")
            return None
        except Exception as e:
            logger.debug(f"OpenAlex fetch error: {e}")
            return None

    def parse_openalex_work(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse OpenAlex work data into standardized metadata.

        Args:
            data: Raw OpenAlex API response.

        Returns:
            Standardized metadata dict with title, year, authors, venue, abstract,
            citation_count, doi, arxiv_id, openalex_id, referenced_works.
        """
        # Extract basic fields
        title = data.get("title")
        year = data.get("publication_year")
        citation_count = data.get("cited_by_count")

        # Extract authors (limit to 10)
        authors = []
        for authorship in data.get("authorships", [])[:10]:
            author = authorship.get("author", {})
            name = author.get("display_name")
            if name:
                authors.append(name)

        # Extract venue
        venue = None
        primary_location = data.get("primary_location", {})
        if primary_location:
            source = primary_location.get("source", {})
            if source:
                venue = source.get("display_name")

        # Reconstruct abstract
        abstract = self.reconstruct_abstract(data.get("abstract_inverted_index"))

        # Extract DOI
        doi = data.get("doi")
        if doi:
            if doi.startswith("https://doi.org/"):
                doi = doi[16:]
            elif doi.startswith("http://doi.org/"):
                doi = doi[15:]

        # Extract arXiv ID from IDs
        arxiv_id = None
        for id_obj in data.get("ids", {}).values():
            if isinstance(id_obj, str) and "arxiv.org" in id_obj:
                parts = id_obj.split("/")
                if len(parts) >= 2:
                    arxiv_id = parts[-1]
                    break

        # Extract OpenAlex ID
        openalex_id = data.get("id", "")
        if openalex_id:
            openalex_id = openalex_id.replace("https://openalex.org/", "")

        # Extract referenced works
        refs = data.get("referenced_works", [])
        refs_clean = [ref.replace("https://openalex.org/", "") for ref in refs]

        return {
            "title": title,
            "year": year,
            "authors": authors if authors else None,
            "venue": venue,
            "abstract": abstract,
            "citation_count": citation_count,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "openalex_id": openalex_id,
            "referenced_works": refs_clean,
        }

    @staticmethod
    def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index format.

        Args:
            inverted_index: OpenAlex abstract_inverted_index field.

        Returns:
            Reconstructed abstract string, or None if not available.
        """
        if not inverted_index:
            return None

        try:
            # Find max position
            max_pos = 0
            for positions in inverted_index.values():
                if positions:
                    max_pos = max(max_pos, max(positions))

            # Build word list
            words = [""] * (max_pos + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            return " ".join(words)
        except Exception:
            return None


class CrossRefMixin:
    """Mixin providing CrossRef API fetching functionality.

    Requires the class to have:
    - _client: httpx.AsyncClient
    - _semaphore: asyncio.Semaphore
    - delay: float
    """

    crossref_email: str | None = None
    _client: httpx.AsyncClient | None = None
    _semaphore: asyncio.Semaphore | None = None
    delay: float = 0.1

    def _init_crossref(self, email: str | None = None) -> None:
        """Initialize CrossRef credentials.

        Args:
            email: Email for polite pool. Uses CROSSREF_EMAIL env if not set.
        """
        self.crossref_email = email or get_crossref_email()

    def _get_crossref_headers(self) -> dict[str, str]:
        """Get headers for CrossRef API calls."""
        headers = {
            "User-Agent": "LexiconArxiv/1.0 (Academic paper indexing; https://github.com/lexicon-arxiv)"
        }
        return headers

    async def fetch_crossref_work(
        self,
        doi: str,
        max_retries: int = 3,
    ) -> dict[str, Any] | None:
        """Fetch paper metadata from CrossRef by DOI.

        Args:
            doi: The DOI to look up (without 'doi:' prefix).
            max_retries: Maximum retries for rate limiting.

        Returns:
            CrossRef message data or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        url = f"{CROSSREF_BASE_URL}/works/{doi}"
        headers = self._get_crossref_headers()
        params = {}
        if self.crossref_email:
            params["mailto"] = self.crossref_email

        for attempt in range(max_retries):
            try:
                async with self._semaphore:
                    response = await self._client.get(url, headers=headers, params=params)
                    await asyncio.sleep(self.delay)

                if response.status_code == 404:
                    return None

                if response.status_code == 429:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.warning(
                        f"CrossRef rate limited, waiting {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()
                return data.get("message")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return None
                if e.response.status_code == 429:
                    wait_time = 2**attempt
                    logger.warning(
                        f"CrossRef rate limited, waiting {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.debug(f"CrossRef HTTP error for {doi}: {e}")
                return None
            except Exception as e:
                logger.debug(f"CrossRef error for {doi}: {e}")
                return None

        logger.warning(f"CrossRef max retries exceeded for {doi}")
        return None

    def parse_crossref_work(self, message: dict[str, Any]) -> dict[str, Any]:
        """Parse CrossRef work data into standardized metadata.

        Args:
            message: CrossRef API message data.

        Returns:
            Standardized metadata dict.
        """
        # Extract title
        titles = message.get("title", [])
        title = titles[0] if titles else None

        # Extract year
        year = None
        published = message.get("published", {}) or message.get("published-print", {})
        date_parts = published.get("date-parts", [[]])
        if date_parts and date_parts[0]:
            year = date_parts[0][0]

        # Extract authors (limit to 10)
        authors = []
        for author in message.get("author", [])[:10]:
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        # Extract venue
        venue = None
        container = message.get("container-title", [])
        if container:
            venue = container[0]

        # Extract references
        references = []
        for ref in message.get("reference", []):
            if ref.get("DOI"):
                references.append(f"doi:{ref['DOI']}")
            elif ref.get("unstructured"):
                text = ref["unstructured"][:200]
                references.append(f"title:{text}")
            elif ref.get("article-title"):
                references.append(f"title:{ref['article-title']}")

        return {
            "title": title,
            "year": year,
            "authors": authors if authors else None,
            "venue": venue,
            "abstract": None,  # CrossRef rarely has abstracts
            "citation_count": message.get("is-referenced-by-count"),
            "references": references,
        }
