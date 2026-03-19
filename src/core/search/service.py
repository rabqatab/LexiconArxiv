"""SearchService: orchestrates query embedding + Qdrant hybrid search."""

import logging
import time

import httpx
from qdrant_client import models

from src.core.constants import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_VECTOR_NAME,
    EMBEDDING_VECTOR_SIZE,
    get_ollama_base_url,
)
from src.core.search.on_demand import OnDemandSearch
from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)


class SearchService:
    """Orchestrates hybrid search: embed query + Qdrant prefetch + RRF fusion."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        ollama_base_url: str | None = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        target_dim: int = EMBEDDING_VECTOR_SIZE,
        dense_vector_name: str = EMBEDDING_VECTOR_NAME,
        query_timeout: float = 5.0,
        max_retries: int = 2,
    ):
        self._storage = storage or QdrantStorage()
        self._base_url = ollama_base_url or get_ollama_base_url()
        self._model = model
        self._target_dim = target_dim
        self._dense_vector_name = dense_vector_name
        self._query_timeout = query_timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None
        self._on_demand: OnDemandSearch | None = None

    @property
    def on_demand(self) -> OnDemandSearch | None:
        return self._on_demand

    @property
    def storage(self) -> QdrantStorage:
        return self._storage

    async def __aenter__(self) -> "SearchService":
        self._client = httpx.AsyncClient(timeout=self._query_timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _embed_query(self, query: str) -> list[float] | None:
        """Embed a search query via Ollama. Returns None on failure."""
        if not self._client:
            return None
        instruction = "Retrieve academic papers: "
        for attempt in range(self._max_retries):
            try:
                response = await self._client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": [instruction + query]},
                )
                response.raise_for_status()
                embeddings = response.json()["embeddings"]
                return embeddings[0][: self._target_dim]
            except Exception as e:
                if attempt < self._max_retries - 1:
                    logger.warning(f"Query embed failed (attempt {attempt + 1}): {e}")
                else:
                    logger.warning(f"Query embed failed, falling back to BM25-only: {e}")
                    return None

    def _build_filters(
        self,
        venues: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        tiers: list[int] | None = None,
    ) -> models.Filter | None:
        """Build Qdrant filter from search parameters."""
        must = []
        must_not = [
            # Exclude stubs (is_stub is null on real papers, true on stubs)
            models.FieldCondition(
                key="is_stub", match=models.MatchValue(value=True)
            ),
        ]
        if venues:
            must.append(
                models.FieldCondition(
                    key="venue", match=models.MatchAny(any=venues)
                )
            )
        if year_min is not None:
            must.append(
                models.FieldCondition(
                    key="year", range=models.Range(gte=year_min)
                )
            )
        if year_max is not None:
            must.append(
                models.FieldCondition(
                    key="year", range=models.Range(lte=year_max)
                )
            )
        if tiers:
            must.append(
                models.FieldCondition(
                    key="tier", match=models.MatchAny(any=tiers)
                )
            )
        return models.Filter(must=must if must else None, must_not=must_not)

    async def search(
        self,
        query: str,
        venues: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        tiers: list[int] | None = None,
        section: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Execute hybrid search. Falls back to BM25-only if Ollama unavailable.

        Args:
            section: Optional section to target (task, method, result, etc.).
                     Uses section-specific vector for dense search.
        """
        start = time.time()
        qdrant_filter = self._build_filters(venues, year_min, year_max, tiers)

        query_vector = await self._embed_query(query)
        search_mode = "hybrid" if query_vector is not None else "bm25_only"

        # Choose dense vector based on section target
        if section and section in ("task", "domain", "background", "approach", "method", "result", "contribution"):
            dense_name = f"section-{section}"
        else:
            dense_name = "structured-abstract"  # Primary: section-prefixed vector

        if search_mode == "hybrid":
            prefetch = [
                models.Prefetch(
                    query=query_vector,
                    using=dense_name,
                    filter=qdrant_filter,
                    limit=limit + offset,
                ),
                models.Prefetch(
                    query=models.Document(text=query, model="qdrant/bm25"),
                    using="bm25",
                    filter=qdrant_filter,
                    limit=limit + offset,
                ),
            ]
            results = self._storage.client.query_points(
                collection_name=self._storage.collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit + offset,
                with_payload=True,
            )
        else:
            results = self._storage.client.query_points(
                collection_name=self._storage.collection_name,
                query=models.Document(text=query, model="qdrant/bm25"),
                using="bm25",
                query_filter=qdrant_filter,
                limit=limit + offset,
                with_payload=True,
            )

        points = results.points[offset:]

        items = []
        for point in points:
            p = point.payload or {}
            items.append({
                "id": str(point.id),
                "title": p.get("title", ""),
                "abstract": p.get("abstract"),
                "authors": p.get("authors", []),
                "venue": p.get("venue"),
                "year": p.get("year"),
                "tier": p.get("tier"),
                "doi": p.get("doi"),
                "citation_count": p.get("citation_count", 0),
                "pagerank": p.get("pagerank"),
                "keywords": p.get("keywords", []),
                "code_url": p.get("code_url"),
                "pdf_url": p.get("pdf_url"),
                "score": round(point.score, 4) if point.score else 0.0,
            })

        total = self._storage.client.count(
            self._storage.collection_name,
            count_filter=qdrant_filter,
        ).count

        elapsed_ms = int((time.time() - start) * 1000)

        return {
            "results": items,
            "total": total,
            "query_time_ms": elapsed_ms,
            "search_mode": search_mode,
            "on_demand_available": self._on_demand is not None,
        }

    async def get_paper(self, paper_id: str) -> dict | None:
        """Get full paper detail by point ID."""
        try:
            points = self._storage.client.retrieve(
                collection_name=self._storage.collection_name,
                ids=[paper_id],
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return None
            p = points[0].payload or {}
            return {
                "id": str(points[0].id),
                "title": p.get("title", ""),
                "abstract": p.get("abstract"),
                "authors": p.get("authors", []),
                "venue": p.get("venue"),
                "year": p.get("year"),
                "tier": p.get("tier"),
                "doi": p.get("doi"),
                "arxiv_id": p.get("arxiv_id"),
                "citation_count": p.get("citation_count", 0),
                "pagerank": p.get("pagerank"),
                "keywords": p.get("keywords", []),
                "keywords_structured": p.get("keywords_structured"),
                "abstract_structure": p.get("abstract_structure"),
                "code_repositories": p.get("code_repositories", []),
                "code_url": p.get("code_url"),
                "pdf_url": p.get("pdf_url"),
                "is_core": p.get("is_core", False),
                "is_stub": p.get("is_stub", False),
                "reference_count": len(p.get("resolved_references", [])),
                "cited_by_count": len(p.get("cited_by", [])),
            }
        except Exception as e:
            logger.error(f"Failed to get paper {paper_id}: {e}")
            return None

    async def init_on_demand(self) -> None:
        """Initialize on-demand search (arXiv + OpenAlex clients)."""
        self._on_demand = OnDemandSearch(storage=self._storage)
        await self._on_demand.__aenter__()

    async def shutdown_on_demand(self) -> None:
        """Cleanup on-demand search clients."""
        if self._on_demand:
            await self._on_demand.__aexit__(None, None, None)
            self._on_demand = None

    async def expand_search(
        self,
        query: str,
        sources: str = "both",
        limit: int = 20,
    ) -> dict:
        """Expand search to arXiv + OpenAlex."""
        if self._on_demand is None:
            return {"error": "On-demand search not available"}
        return await self._on_demand.expand(query=query, sources=sources, limit=limit)

    async def check_ollama_available(self) -> bool:
        """Check if Ollama is running and has the embedding model."""
        if not self._client:
            return False
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            model_list = response.json().get("models", [])
            return any(self._model in m.get("name", "") for m in model_list)
        except Exception:
            return False
