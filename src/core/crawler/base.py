"""Base classes for crawler modules.

Provides shared functionality for async HTTP client management,
checkpointing, and deduplication across all crawlers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx

from src.core.checkpoint import CheckpointManager
from src.core.deduplication import Deduplicator
from src.models.paper import PaperType, RawPaper

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


class BaseCrawler(ABC):
    """Abstract base class for all paper crawlers.

    Provides:
    - Async context management with httpx client
    - Storage, checkpoint, and deduplication instances
    - Common configuration (timeout)
    """

    # Subclasses can override these
    DEFAULT_TIMEOUT = 60.0
    DEFAULT_USER_AGENT = "LexiconArxiv/1.0 (Academic paper collection)"

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        timeout: float | None = None,
        checkpoint_name: str | None = None,
    ):
        """Initialize BaseCrawler.

        Args:
            storage: QdrantStorage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
                Pass a shared instance for cross-source deduplication.
            timeout: HTTP request timeout in seconds.
            checkpoint_name: Name for checkpoint file (defaults to class name).
        """
        from src.core.storage import QdrantStorage

        self.storage = storage or QdrantStorage()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(
            checkpoint_name=checkpoint_name or self.__class__.__name__.lower()
        )
        self.deduplicator = deduplicator or Deduplicator(storage=self.storage)
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseCrawler":
        """Enter async context, creating HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self._get_default_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context, closing HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_default_headers(self) -> dict[str, str]:
        """Get default HTTP headers. Subclasses can override."""
        return {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError(
                "HTTP client not initialized. Use 'async with' context manager."
            )
        return self._client

    @abstractmethod
    async def collect_venue(
        self,
        venue: str,
        since_year: int | None = None,
        **kwargs,
    ) -> AsyncIterator[RawPaper]:
        """Collect papers from a specific venue.

        Args:
            venue: Venue identifier.
            since_year: Only collect papers from this year onwards.
            **kwargs: Additional source-specific arguments.

        Yields:
            RawPaper instances.
        """
        pass

    @abstractmethod
    async def collect_all(
        self,
        since_year: int | None = None,
        **kwargs,
    ) -> AsyncIterator[RawPaper]:
        """Collect papers from all configured venues.

        Args:
            since_year: Only collect papers from this year onwards.
            **kwargs: Additional source-specific arguments.

        Yields:
            RawPaper instances.
        """
        pass


def classify_paper_type_by_title(title: str) -> PaperType:
    """Classify paper type based on title keywords.

    This provides common title-based classification logic that can be
    used by all crawlers as a fallback or supplement to source-specific
    classification.

    Args:
        title: Paper title.

    Returns:
        PaperType enum value.
    """
    title_lower = title.lower() if title else ""

    # Survey/Review papers
    if any(kw in title_lower for kw in ["survey", "review", "overview", "tutorial"]):
        return PaperType.SURVEY

    # Dataset/Benchmark papers
    if any(kw in title_lower for kw in ["dataset", "corpus", "benchmark"]):
        return PaperType.DATASET

    # Demo papers
    if any(kw in title_lower for kw in ["demo", "demonstration", "system demo"]):
        return PaperType.DEMO

    # Position/Perspective papers
    if any(kw in title_lower for kw in ["position", "perspective", "opinion"]):
        return PaperType.POSITION

    # Analysis/Empirical papers
    if any(kw in title_lower for kw in ["analysis", "empirical study", "study of"]):
        return PaperType.ANALYSIS

    # Default to Method
    return PaperType.METHOD
