"""Base collector interface for paper data sources."""

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.models.paper import RawPaper, SourceType

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """Base exception for collector errors."""

    pass


class RateLimitError(CollectorError):
    """Raised when rate limit is exceeded."""

    pass


class APIError(CollectorError):
    """Raised when API returns an error."""

    pass


class BaseCollector(ABC):
    """Abstract base class for paper collectors.

    Provides common functionality for HTTP requests, rate limiting, and error handling.
    """

    # Override in subclasses
    SOURCE_TYPE: SourceType
    BASE_URL: str
    DEFAULT_TIMEOUT: float = 30.0
    MAX_RETRIES: int = 3

    def __init__(
        self,
        timeout: float | None = None,
        email: str | None = None,
    ):
        """Initialize the collector.

        Args:
            timeout: Request timeout in seconds.
            email: Contact email for polite API access.
        """
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.email = email
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseCollector":
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
        """Get default headers for requests."""
        headers = {
            "User-Agent": "LexiconArxiv/0.1.0 (Paper Search Engine)",
        }
        if self.email:
            headers["User-Agent"] += f" mailto:{self.email}"
        return headers

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, raising error if not in context."""
        if self._client is None:
            raise RuntimeError(
                "Collector must be used as async context manager: "
                "async with Collector() as collector: ..."
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method.
            url: Request URL.
            **kwargs: Additional arguments for httpx.

        Returns:
            HTTP response.

        Raises:
            RateLimitError: If rate limit is exceeded.
            APIError: If API returns an error.
        """
        response = await self.client.request(method, url, **kwargs)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            logger.warning(f"Rate limited, retry after {retry_after}s")
            raise RateLimitError(f"Rate limit exceeded, retry after {retry_after}s")

        if response.status_code >= 400:
            raise APIError(f"API error {response.status_code}: {response.text[:200]}")

        return response

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Make a GET request."""
        return await self._request("GET", url, **kwargs)

    @abstractmethod
    async def search(self, query: str, limit: int = 100) -> list[RawPaper]:
        """Search for papers matching the query.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of papers matching the query.
        """
        pass

    @abstractmethod
    async def fetch_by_id(self, paper_id: str) -> RawPaper | None:
        """Fetch a single paper by its source-specific ID.

        Args:
            paper_id: The paper ID in the source system.

        Returns:
            The paper if found, None otherwise.
        """
        pass

    async def collect_all(
        self,
        query: str | None = None,
        batch_size: int = 100,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect all papers matching criteria, yielding batches.

        Args:
            query: Optional search query to filter papers.
            batch_size: Number of papers per batch.

        Yields:
            Batches of papers.
        """
        # Default implementation using search with pagination
        # Subclasses can override for more efficient bulk collection
        offset = 0
        while True:
            papers = await self.search(query or "", limit=batch_size)
            if not papers:
                break
            yield papers
            offset += len(papers)
            if len(papers) < batch_size:
                break

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the human-readable name of this source."""
        pass
