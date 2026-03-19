"""Dependency injection for the Graph API.

Provides shared services like storage, citation index, and graph builder.
Uses lazy initialization to avoid blocking startup.
"""

import logging
from functools import lru_cache

from src.core.citation_graph.builder import CitationGraphBuilder
from src.core.citation_graph.reverse_index import ReverseCitationIndex
from src.core.search.service import SearchService
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


class GraphServices:
    """Container for graph-related services with lazy initialization.

    The citation index is pre-built at startup (via lifespan), but other
    services are initialized lazily on first use.
    """

    def __init__(self):
        """Initialize the services container."""
        self._storage: QdrantStorage | None = None
        self._index: ReverseCitationIndex | None = None
        self._builder: CitationGraphBuilder | None = None
        self._search_service: SearchService | None = None

    @property
    def storage(self) -> QdrantStorage:
        """Get or create the Qdrant storage instance."""
        if self._storage is None:
            self._storage = QdrantStorage()
        return self._storage

    @property
    def index(self) -> ReverseCitationIndex:
        """Get the pre-built citation index.

        Raises:
            RuntimeError: If the index hasn't been built yet.
        """
        if self._index is None:
            raise RuntimeError("Citation index not initialized. Call build_index() first.")
        return self._index

    @property
    def builder(self) -> CitationGraphBuilder:
        """Get or create the graph builder instance."""
        if self._builder is None:
            # Use the pre-built index if available
            self._builder = CitationGraphBuilder(
                storage=self.storage,
                reverse_index=self._index,
            )
        return self._builder

    def build_index(self, include_metadata: bool = True) -> None:
        """Build the reverse citation index.

        Should be called during application startup.

        Args:
            include_metadata: Whether to cache paper metadata in the index.
        """
        logger.info("Building reverse citation index...")
        self._index = ReverseCitationIndex(self.storage)
        self._index.build_index(include_metadata=include_metadata)
        logger.info("Citation index ready")

        # Ensure builder uses the new index
        self._builder = None

    async def init_search_service(self) -> None:
        """Initialize the search service (requires event loop)."""
        self._search_service = SearchService(storage=self.storage)
        await self._search_service.__aenter__()
        available = await self._search_service.check_ollama_available()
        if available:
            logger.info("Search service ready (hybrid mode)")
        else:
            logger.warning("Ollama unavailable — search will use BM25-only mode")
        await self._search_service.init_on_demand()
        logger.info("On-demand search initialized (arXiv + OpenAlex)")

    async def shutdown_search_service(self) -> None:
        """Cleanup search service on shutdown."""
        if self._search_service:
            await self._search_service.shutdown_on_demand()
            await self._search_service.__aexit__(None, None, None)
            self._search_service = None

    @property
    def search_service(self) -> SearchService:
        """Get the search service."""
        if self._search_service is None:
            raise RuntimeError("Search service not initialized. Call init_search_service() first.")
        return self._search_service

    @property
    def is_index_built(self) -> bool:
        """Check if the citation index has been built."""
        return self._index is not None and self._index._is_built

    def is_storage_connected(self) -> bool:
        """Check if Qdrant storage is accessible."""
        try:
            self.storage.client.get_collection(self.storage.collection_name)
            return True
        except Exception:
            return False


# Global singleton for services
_services: GraphServices | None = None


@lru_cache
def get_services() -> GraphServices:
    """Get the global GraphServices instance.

    Returns:
        The shared GraphServices instance.
    """
    global _services
    if _services is None:
        _services = GraphServices()
    return _services


def reset_services() -> None:
    """Reset the global services (for testing)."""
    global _services
    _services = None
    get_services.cache_clear()
