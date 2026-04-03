"""SearchService: orchestrates query embedding + Qdrant hybrid search."""

from __future__ import annotations

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
from src.core.search.config import RetrievalConfig
from src.core.search.on_demand import OnDemandSearch
from src.core.search.postprocess import apply_citation_boost, apply_mmr
from src.core.search.query_analyzer import (
    detect_intent,
    generate_hyde,
    generate_query_variants,
)
from src.core.search.venue_map import expand_venue_names
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
        self._reranker = None  # Optional Reranker instance

    @property
    def on_demand(self) -> OnDemandSearch | None:
        return self._on_demand

    @property
    def reranker(self):
        return self._reranker

    async def init_reranker(self) -> None:
        """Load the cross-encoder reranker model."""
        from src.core.search.reranker import Reranker

        self._reranker = Reranker()
        self._reranker.load()

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
            # Expand short names (e.g. "ICLR") into all matching patterns,
            # then use MatchText for substring matching so that "ICLR"
            # matches "ICLR 2025 Poster", "ICLR 2024 poster", etc.
            patterns = expand_venue_names(venues)
            if len(patterns) == 1:
                must.append(
                    models.FieldCondition(
                        key="venue",
                        match=models.MatchText(text=patterns[0]),
                    )
                )
            else:
                # Multiple patterns: combine with OR (should) inside must
                venue_conditions = [
                    models.FieldCondition(
                        key="venue",
                        match=models.MatchText(text=p),
                    )
                    for p in patterns
                ]
                must.append(models.Filter(should=venue_conditions))
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
        config: RetrievalConfig | None = None,
    ) -> dict:
        """Execute the advanced retrieval pipeline.

        Stages:
            1. Query analysis (intent detection, HyDE, RAG-Fusion)
            2. Multi-vector retrieval
            3. RRF fusion (always on)
            4. Cross-encoder reranking (optional)
            5. Post-processing (citation boost, MMR diversity)

        Falls back to BM25-only if Ollama is unavailable.

        Args:
            section: Optional section to target (task, method, result, etc.).
                     Uses section-specific vector for dense search.
            config: Pipeline configuration. Defaults to ``RetrievalConfig()``
                    which preserves backward-compatible behaviour.
        """
        cfg = config or RetrievalConfig()
        pipeline_info: dict = {"stages_applied": [], "vectors_searched": []}
        start = time.time()

        qdrant_filter = self._build_filters(venues, year_min, year_max, tiers)

        # ------------------------------------------------------------------
        # Stage 1: Query Analysis
        # ------------------------------------------------------------------
        analyzed_section = section
        queries: list[str] = [query]

        if cfg.query_intent and not section:
            intent = detect_intent(query)
            analyzed_section = intent.get("target_section")
            pipeline_info["query_analysis"] = intent
            pipeline_info["stages_applied"].append("query_intent")

        if cfg.hyde and self._client:
            hyde_text = await generate_hyde(query, self._client, self._base_url)
            if hyde_text:
                queries.append(hyde_text)
                pipeline_info["stages_applied"].append("hyde")

        if cfg.rag_fusion and self._client:
            variants = await generate_query_variants(
                query, self._client, self._base_url
            )
            queries.extend(variants)
            pipeline_info["stages_applied"].append("rag_fusion")

        # ------------------------------------------------------------------
        # Stage 2: Multi-vector retrieval
        # ------------------------------------------------------------------
        retrieve_limit = cfg.rerank_top_k if cfg.reranker else (limit + offset)

        # Determine which dense vector(s) to query
        if analyzed_section and analyzed_section in (
            "task", "domain", "background", "approach", "method", "result", "contribution",
        ):
            dense_names = [f"section-{analyzed_section}"]
        elif cfg.multi_vector:
            dense_names = list(cfg.multi_vector_names)
        else:
            dense_names = ["structured-abstract"]

        # Embed all queries and build prefetch list
        prefetch: list[models.Prefetch] = []
        has_dense = False

        for q in queries:
            query_vector = await self._embed_query(q)
            if query_vector is not None:
                has_dense = True
                for vn in dense_names:
                    prefetch.append(
                        models.Prefetch(
                            query=query_vector,
                            using=vn,
                            filter=qdrant_filter,
                            limit=retrieve_limit,
                        )
                    )
                    if vn not in pipeline_info["vectors_searched"]:
                        pipeline_info["vectors_searched"].append(vn)

        # BM25 for each query
        for q in queries:
            prefetch.append(
                models.Prefetch(
                    query=models.Document(text=q, model="qdrant/bm25"),
                    using="bm25",
                    filter=qdrant_filter,
                    limit=retrieve_limit,
                )
            )
        if "bm25" not in pipeline_info["vectors_searched"]:
            pipeline_info["vectors_searched"].append("bm25")

        search_mode = "hybrid" if has_dense else "bm25_only"

        # ------------------------------------------------------------------
        # Stage 3: RRF Fusion (always on)
        # ------------------------------------------------------------------
        if prefetch:
            results = self._storage.client.query_points(
                collection_name=self._storage.collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=retrieve_limit,
                with_payload=True,
            )
        else:
            # Fallback: single BM25 query (no prefetch)
            results = self._storage.client.query_points(
                collection_name=self._storage.collection_name,
                query=models.Document(text=query, model="qdrant/bm25"),
                using="bm25",
                query_filter=qdrant_filter,
                limit=retrieve_limit,
                with_payload=True,
            )

        # Convert Qdrant points to dicts
        items: list[dict] = []
        for point in results.points:
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
                "abstract_structure": p.get("abstract_structure"),
                "code_url": p.get("code_url"),
                "pdf_url": p.get("pdf_url"),
                "score": round(point.score, 4) if point.score else 0.0,
            })

        # ------------------------------------------------------------------
        # Stage 4: Reranking
        # ------------------------------------------------------------------
        if cfg.reranker and self._reranker and self._reranker.is_loaded:
            items = self._reranker.rerank(query, items, top_k=limit + offset)
            pipeline_info["stages_applied"].append("reranker")

        # ------------------------------------------------------------------
        # Stage 5: Post-processing
        # ------------------------------------------------------------------
        if cfg.citation_boost:
            items = apply_citation_boost(
                items, cfg.citation_alpha, cfg.citation_beta, cfg.citation_gamma
            )
            pipeline_info["stages_applied"].append("citation_boost")

        if cfg.mmr_diversity:
            items = apply_mmr(items, cfg.mmr_lambda, limit=limit + offset)
            pipeline_info["stages_applied"].append("mmr_diversity")

        # Apply offset/limit after all post-processing
        items = items[offset : offset + limit]

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
            "pipeline": pipeline_info,
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
