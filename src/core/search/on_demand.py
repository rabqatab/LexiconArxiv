"""On-demand search expansion via arXiv + OpenAlex."""

import asyncio
import hashlib
import logging
import time

from cachetools import TTLCache

from src.core.search.arxiv_client import ArxivClient
from src.core.search.openalex_client import OpenAlexSearchClient
from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)


class OnDemandSearch:
    """Orchestrates on-demand expansion: query external sources, dedup, label connections."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        cache_maxsize: int = 1000,
        cache_ttl: int = 86400,  # 24 hours
    ):
        self._storage = storage or QdrantStorage()
        self._cache: TTLCache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._cache_lock = asyncio.Lock()
        self._arxiv: ArxivClient | None = None
        self._openalex: OpenAlexSearchClient | None = None

    async def __aenter__(self) -> "OnDemandSearch":
        self._arxiv = ArxivClient()
        await self._arxiv.__aenter__()
        self._openalex = OpenAlexSearchClient()
        await self._openalex.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        if self._arxiv:
            await self._arxiv.__aexit__(*args)
        if self._openalex:
            await self._openalex.__aexit__(*args)

    async def expand(
        self,
        query: str,
        sources: str = "both",  # "arxiv", "openalex", "both"
        limit: int = 20,
    ) -> dict:
        """Expand search with external results.

        Args:
            query: Search query string.
            sources: Which sources to query — "arxiv", "openalex", or "both".
            limit: Maximum number of results to return.

        Returns:
            Dictionary with expanded_results, expansion_stats, query_time_ms, cached.
        """
        start = time.time()

        # Check cache
        cache_key = self._cache_key(query, sources, limit)
        async with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            cached["cached"] = True
            cached["query_time_ms"] = 0
            return cached

        # Query external sources in parallel
        arxiv_results: list[dict] = []
        openalex_results: list[dict] = []

        coros = []
        source_map: list[str] = []
        if sources in ("arxiv", "both") and self._arxiv:
            coros.append(self._arxiv.search(query, max_results=limit))
            source_map.append("arxiv")
        if sources in ("openalex", "both") and self._openalex:
            coros.append(self._openalex.search(query, max_results=limit))
            source_map.append("openalex")

        gathered = await asyncio.gather(*coros, return_exceptions=True)

        for i, result in enumerate(gathered):
            if isinstance(result, Exception):
                logger.error(f"{source_map[i]} search failed: {result}")
                continue
            if source_map[i] == "arxiv":
                arxiv_results = result
            else:
                openalex_results = result

        # Dedup and label
        all_external = arxiv_results + openalex_results
        deduped, dedup_count = self._deduplicate(all_external)
        labeled = self._label_connections(deduped)

        # Count stats
        connected_count = sum(1 for r in labeled if r["connection"] == "connected")
        external_count = sum(1 for r in labeled if r["connection"] == "external")

        elapsed_ms = int((time.time() - start) * 1000)

        result = {
            "expanded_results": labeled[:limit],
            "expansion_stats": {
                "arxiv_fetched": len(arxiv_results),
                "openalex_fetched": len(openalex_results),
                "deduplicated": dedup_count,
                "connected": connected_count,
                "external": external_count,
            },
            "query_time_ms": elapsed_ms,
            "cached": False,
        }

        # Cache result
        async with self._cache_lock:
            self._cache[cache_key] = result

        return result

    def _cache_key(self, query: str, sources: str, limit: int) -> str:
        """Generate a cache key from query params."""
        raw = f"{query.lower().strip()}:{sources}:{limit}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _deduplicate(self, results: list[dict]) -> tuple[list[dict], int]:
        """Remove duplicates and papers already in the core corpus.

        Returns:
            Tuple of (deduplicated results, number of items removed).
        """
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        removed = 0

        for paper in results:
            doi = paper.get("doi")
            arxiv_id = paper.get("arxiv_id")

            # Dedup by DOI or arXiv ID within results
            key = doi or arxiv_id or paper.get("title", "").lower().strip()
            if key in seen_ids:
                removed += 1
                continue
            seen_ids.add(key)

            # Check if paper exists in core corpus
            is_core = False
            if doi:
                existing = self._storage.queries.get_paper_by_doi(doi)
                if existing:
                    is_core = True
            if not is_core and arxiv_id:
                existing = self._storage.queries.get_paper_by_arxiv_id(arxiv_id)
                if existing:
                    is_core = True

            if is_core:
                paper["connection"] = "core"
                removed += 1  # Count as dedup since it's already in corpus
            else:
                paper["connection"] = "external"  # Will be re-labeled in _label_connections

            deduped.append(paper)

        return deduped, removed

    def _label_connections(self, results: list[dict]) -> list[dict]:
        """Label papers as connected if they cite or are cited by core papers."""
        labeled = []
        for paper in results:
            if paper.get("connection") == "core":
                paper["connected_papers"] = []
                labeled.append(paper)
                continue

            # Check if this paper is cited by any core paper (check stub index)
            doi = paper.get("doi")
            connected_papers = []

            if doi:
                stub = self._storage.stubs.get_stub_by_identifier(f"doi:{doi}")
                if stub:
                    _stub_id, stub_payload = stub
                    cited_by = stub_payload.get("cited_by", [])
                    for citing_id in cited_by[:3]:  # Limit to 3 connections
                        try:
                            points = self._storage.client.retrieve(
                                self._storage.collection_name,
                                ids=[citing_id],
                                with_payload=["title"],
                            )
                            if points:
                                connected_papers.append({
                                    "id": citing_id,
                                    "title": points[0].payload.get("title", "Unknown"),
                                    "relation": "cited_by",
                                })
                        except Exception:
                            pass

            if connected_papers:
                paper["connection"] = "connected"
                paper["connected_papers"] = connected_papers
            else:
                paper["connection"] = "external"
                paper["connected_papers"] = []

            labeled.append(paper)

        return labeled
