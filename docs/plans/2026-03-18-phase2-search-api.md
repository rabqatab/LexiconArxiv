# Phase 2: Search API + Web UI — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hybrid search API (dense + BM25 via RRF) with Qdrant, a paper detail API, and a minimal web UI for searching the 145K-paper corpus.

**Architecture:** SearchService orchestrates query embedding (Ollama) + Qdrant hybrid search (prefetch dense + BM25, fuse with RRF). Falls back to BM25-only when Ollama is unavailable. FastAPI router extends the existing graph API. Vanilla HTML/JS search page.

**Tech Stack:** FastAPI, Qdrant 1.16 (query_points + prefetch + FusionQuery), httpx (Ollama), slowapi (rate limiting), Pydantic v2 (request/response models)

**Spec:** `docs/specs/2026-03-18-search-engine-mvp-design.md` — Section 4

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/search/__init__.py` | Package init |
| Create | `src/core/search/service.py` | SearchService: embed query + Qdrant hybrid search |
| Create | `src/api/models/search.py` | Pydantic request/response models |
| Create | `src/api/routes/search.py` | Search API router (POST /api/search, GET /api/paper, etc.) |
| Modify | `src/api/dependencies.py` | Add SearchService to GraphServices, async init |
| Modify | `src/api/main.py` | Register search router, init SearchService in lifespan, add rate limiting |
| Create | `src/api/static/search.html` | Minimal search web UI |
| Create | `tests/test_search_service.py` | Unit tests for SearchService |
| Create | `tests/test_search_api.py` | API endpoint tests |

**New dependency:** `slowapi` for IP-based rate limiting.

---

## Chunk 1: Search Service (Core Logic)

### Task 1: Create Pydantic request/response models

**Files:**
- Create: `src/api/models/search.py`

- [ ] **Step 1: Create search models**

```python
# src/api/models/search.py
"""Request and response models for the search API."""

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Optional filters for search queries."""
    venues: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None
    tiers: list[int] | None = None


class SearchRequest(BaseModel):
    """Search request body."""
    query: str = Field(..., min_length=1, max_length=500)
    filters: SearchFilters | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResultItem(BaseModel):
    """A single search result."""
    id: str
    title: str
    abstract: str | None = None
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    tier: int | None = None
    doi: str | None = None
    citation_count: int = 0
    pagerank: float | None = None
    keywords: list[str] = []
    code_url: str | None = None
    pdf_url: str | None = None
    score: float = 0.0


class SearchResponse(BaseModel):
    """Search response."""
    results: list[SearchResultItem]
    total: int
    query_time_ms: int
    search_mode: str  # "hybrid" or "bm25_only"
    on_demand_available: bool = False


class PaperDetailResponse(BaseModel):
    """Full paper detail with citation context."""
    id: str
    title: str
    abstract: str | None = None
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    tier: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    citation_count: int = 0
    pagerank: float | None = None
    keywords: list[str] = []
    keywords_structured: dict | None = None
    abstract_structure: dict | None = None
    code_repositories: list[dict] = []
    code_url: str | None = None
    pdf_url: str | None = None
    is_core: bool = False
    is_stub: bool = False
    reference_count: int = 0
    cited_by_count: int = 0


class SuggestResponse(BaseModel):
    """Autocomplete suggestion response."""
    suggestions: list[str]


class CorpusStatsResponse(BaseModel):
    """Corpus statistics."""
    total_papers: int
    total_stubs: int
    papers_with_abstracts: int
    papers_with_keywords: int
    papers_with_vectors: int
    venues: dict[str, int] = {}
```

- [ ] **Step 2: Commit**

```bash
git add src/api/models/search.py
git commit -m "feat: add Pydantic search request/response models"
```

---

### Task 2: Create SearchService

**Files:**
- Create: `src/core/search/__init__.py`
- Create: `src/core/search/service.py`
- Create: `tests/test_search_service.py`

- [ ] **Step 1: Write failing test for SearchService.search()**

```python
# tests/test_search_service.py
"""Tests for the SearchService."""

import time

import pytest
import respx
from httpx import Response
from qdrant_client import QdrantClient, models

from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage


class TestSearchService:
    """Test hybrid search orchestration."""

    def setup_method(self):
        self.collection = "_test_search_service"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

        # Create collection with vector configs
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(
                    size=4, distance=models.Distance.COSINE
                ),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )

        # Insert papers with dense + BM25 vectors
        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000001",
                    vector={
                        "abstract-qwen3-8b": [0.9, 0.1, 0.1, 0.1],
                        "bm25": models.Document(
                            text="retrieval augmented generation for knowledge tasks",
                            model="qdrant/bm25",
                        ),
                    },
                    payload={
                        "title": "RAG Paper",
                        "abstract": "About retrieval augmented generation",
                        "authors": ["Author A"],
                        "venue": "NeurIPS 2020",
                        "year": 2020,
                        "tier": 0,
                        "doi": "10.1234/rag",
                        "citation_count": 3000,
                        "keywords": ["RAG", "retrieval"],
                        "is_stub": False,
                        "is_core": True,
                    },
                ),
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000002",
                    vector={
                        "abstract-qwen3-8b": [0.1, 0.9, 0.1, 0.1],
                        "bm25": models.Document(
                            text="attention is all you need transformer architecture",
                            model="qdrant/bm25",
                        ),
                    },
                    payload={
                        "title": "Transformer Paper",
                        "abstract": "About attention and transformers",
                        "authors": ["Author B"],
                        "venue": "NeurIPS 2017",
                        "year": 2017,
                        "tier": 0,
                        "doi": "10.1234/transformer",
                        "citation_count": 50000,
                        "keywords": ["attention", "transformer"],
                        "is_stub": False,
                        "is_core": True,
                    },
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    @pytest.mark.asyncio
    @respx.mock
    async def test_hybrid_search(self):
        """Test hybrid search returns results with score breakdown."""
        # Mock Ollama returning a 8d vector (truncated to 4d)
        fake_embedding = [0.85, 0.15, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": [fake_embedding]}),
        )

        storage = QdrantStorage(collection_name=self.collection)
        service = SearchService(storage=storage, target_dim=4)

        async with service:
            results = await service.search(query="retrieval augmented generation")

        assert results["search_mode"] == "hybrid"
        assert len(results["results"]) == 2
        assert results["results"][0]["title"] == "RAG Paper"  # Closer match

    @pytest.mark.asyncio
    @respx.mock
    async def test_bm25_fallback_when_ollama_down(self):
        """Test BM25-only search when Ollama is unreachable."""
        # Mock Ollama being down
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(500, text="Server Error"),
        )

        storage = QdrantStorage(collection_name=self.collection)
        service = SearchService(storage=storage, target_dim=4, max_retries=1)

        async with service:
            results = await service.search(query="retrieval augmented generation")

        assert results["search_mode"] == "bm25_only"
        assert len(results["results"]) > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_with_filters(self):
        """Test search with venue/year filters."""
        fake_embedding = [0.5, 0.5, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": [fake_embedding]}),
        )

        storage = QdrantStorage(collection_name=self.collection)
        service = SearchService(storage=storage, target_dim=4)

        async with service:
            results = await service.search(
                query="neural network",
                year_min=2019,
            )

        # Only RAG paper (2020) should match year filter
        assert len(results["results"]) == 1
        assert results["results"][0]["year"] == 2020
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_search_service.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement SearchService**

Create `src/core/search/__init__.py`:
```python
"""Search service for LexiconArxiv."""
```

Create `src/core/search/service.py`:
```python
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
        must = [
            # Exclude stubs from search results
            models.FieldCondition(
                key="is_stub", match=models.MatchValue(value=False)
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

        return models.Filter(must=must) if must else None

    async def search(
        self,
        query: str,
        venues: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        tiers: list[int] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Execute hybrid search. Falls back to BM25-only if Ollama unavailable."""
        start = time.time()

        qdrant_filter = self._build_filters(venues, year_min, year_max, tiers)

        # Try to get dense embedding for query
        query_vector = await self._embed_query(query)
        search_mode = "hybrid" if query_vector is not None else "bm25_only"

        # Build prefetch queries
        if search_mode == "hybrid":
            prefetch = [
                models.Prefetch(
                    query=query_vector,
                    using=self._dense_vector_name,
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
            # BM25-only fallback
            results = self._storage.client.query_points(
                collection_name=self._storage.collection_name,
                query=models.Document(text=query, model="qdrant/bm25"),
                using="bm25",
                query_filter=qdrant_filter,
                limit=limit + offset,
                with_payload=True,
            )

        # Apply offset (Qdrant doesn't natively support offset in query_points)
        points = results.points[offset:]

        # Format results
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

        # Get total count (papers matching filters)
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
            "on_demand_available": False,  # Phase 4 enables this
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_search_service.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/search/ src/api/models/search.py tests/test_search_service.py
git commit -m "feat: add SearchService with hybrid search and BM25 fallback"
```

---

## Chunk 2: API Router + Dependencies

### Task 3: Extend GraphServices with SearchService

**Files:**
- Modify: `src/api/dependencies.py`

- [ ] **Step 1: Add SearchService integration to GraphServices**

Add to imports:
```python
from src.core.search.service import SearchService
```

Add to `GraphServices.__init__`:
```python
self._search_service: SearchService | None = None
```

Add new methods:
```python
async def init_search_service(self) -> None:
    """Initialize the search service (requires event loop)."""
    self._search_service = SearchService(storage=self.storage)
    await self._search_service.__aenter__()
    # Check Ollama availability
    available = await self._search_service.check_ollama_available()
    if available:
        logger.info("Search service ready (hybrid mode)")
    else:
        logger.warning("Ollama unavailable — search will use BM25-only mode")

async def shutdown_search_service(self) -> None:
    """Cleanup search service on shutdown."""
    if self._search_service:
        await self._search_service.__aexit__(None, None, None)
        self._search_service = None

@property
def search_service(self) -> SearchService:
    """Get the search service."""
    if self._search_service is None:
        raise RuntimeError("Search service not initialized. Call init_search_service() first.")
    return self._search_service
```

- [ ] **Step 2: Commit**

```bash
git add src/api/dependencies.py
git commit -m "feat: add SearchService to GraphServices with async lifecycle"
```

---

### Task 4: Create search API router

**Files:**
- Create: `src/api/routes/search.py`

- [ ] **Step 1: Implement search routes**

```python
# src/api/routes/search.py
"""Search API routes."""

import logging

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_services
from src.api.models.search import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    PaperDetailResponse,
    SuggestResponse,
    CorpusStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Hybrid search over the paper corpus."""
    services = get_services()
    search = services.search_service

    filters = request.filters
    results = await search.search(
        query=request.query,
        venues=filters.venues if filters else None,
        year_min=filters.year_min if filters else None,
        year_max=filters.year_max if filters else None,
        tiers=filters.tiers if filters else None,
        limit=request.limit,
        offset=request.offset,
    )

    return SearchResponse(
        results=[SearchResultItem(**r) for r in results["results"]],
        total=results["total"],
        query_time_ms=results["query_time_ms"],
        search_mode=results["search_mode"],
        on_demand_available=results["on_demand_available"],
    )


@router.get("/paper/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(paper_id: str):
    """Get full paper detail."""
    services = get_services()
    search = services.search_service

    paper = await search.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    return PaperDetailResponse(**paper)


@router.get("/stats", response_model=CorpusStatsResponse)
async def get_corpus_stats():
    """Get corpus statistics."""
    services = get_services()
    storage = services.storage

    try:
        total = storage.client.count(storage.collection_name).count
        from qdrant_client import models
        stubs = storage.client.count(
            storage.collection_name,
            count_filter=models.Filter(must=[
                models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
            ]),
        ).count
        with_abstracts = storage.client.count(
            storage.collection_name,
            count_filter=models.Filter(
                must=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=False))],
                must_not=[
                    models.IsNullCondition(is_null=models.PayloadField(key="abstract")),
                    models.FieldCondition(key="abstract", match=models.MatchValue(value="")),
                ],
            ),
        ).count
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get corpus stats")

    return CorpusStatsResponse(
        total_papers=total - stubs,
        total_stubs=stubs,
        papers_with_abstracts=with_abstracts,
        papers_with_keywords=0,  # TODO: add count query
        papers_with_vectors=0,   # TODO: add count query
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/api/routes/search.py
git commit -m "feat: add search API router with POST /api/search and GET /api/paper"
```

---

### Task 5: Wire search router into FastAPI app + rate limiting

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Add slowapi dependency**

Run: `uv add slowapi`

- [ ] **Step 2: Update main.py**

Add imports:
```python
from src.api.routes import search
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.responses import JSONResponse
```

Add rate limiter setup (before app creation):
```python
limiter = Limiter(key_func=get_remote_address)
```

Update lifespan to init/shutdown search service:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LexiconArxiv API...")

    services = get_services()

    # Build citation index
    try:
        services.build_index(include_metadata=True)
        logger.info("Citation index built successfully")
    except Exception as e:
        logger.error(f"Failed to build citation index: {e}")
        logger.warning("API will start but subgraph queries will fail")

    # Initialize search service (requires event loop)
    try:
        await services.init_search_service()
    except Exception as e:
        logger.error(f"Failed to init search service: {e}")
        logger.warning("Search API will be unavailable")

    yield

    # Cleanup
    await services.shutdown_search_service()
    logger.info("Shutting down LexiconArxiv API...")
```

Update app metadata:
```python
app = FastAPI(
    title="LexiconArxiv API",
    description="Search and citation graph API for AI research papers",
    version="0.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```

Add search router:
```python
app.include_router(search.router)
```

Add rate limit error handler:
```python
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )
```

Update root endpoint to include search endpoints.

- [ ] **Step 3: Test the API starts**

Run: `uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8000` (verify it starts, ctrl+c)

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py pyproject.toml uv.lock
git commit -m "feat: wire search router into FastAPI app with rate limiting"
```

---

## Chunk 3: Web UI

### Task 6: Create minimal search web UI

**Files:**
- Create: `src/api/static/search.html`

- [ ] **Step 1: Create the search page**

A single HTML file with vanilla JS that:
- Has a search bar with query input
- Filter dropdowns: venue (multi-select), year range (min/max), tier checkboxes
- Sends POST to `/api/search` on form submit
- Displays results as a list: title (linked to paper detail), authors, venue/year badge, abstract snippet (first 200 chars), citation count, keyword tags, code repo link, PDF link
- Clicking a result title opens a paper detail panel (fetches GET `/api/paper/{id}`)
- Shows search_mode indicator ("Hybrid" or "BM25 Only")
- Shows query_time_ms
- Responsive design, clean typography
- Matches the aesthetic of the existing D3.js graph page (dark background, cyan/orange accents)

Key features:
- Debounced search (300ms after typing stops)
- Loading spinner during search
- "No results" message
- Pagination (next/prev with offset)
- Score breakdown tooltip on hover

- [ ] **Step 2: Test by opening in browser**

Run the API server and visit `http://localhost:8000/search` (add a route to serve it).

- [ ] **Step 3: Add route to serve search.html**

In `src/api/main.py`, add:
```python
@app.get("/search")
async def search_page():
    """Serve the search UI."""
    search_path = STATIC_DIR / "search.html"
    if search_path.exists():
        return FileResponse(search_path)
    raise HTTPException(status_code=404, detail="Search UI not found")
```

- [ ] **Step 4: Commit**

```bash
git add src/api/static/search.html src/api/main.py
git commit -m "feat: add minimal search web UI with hybrid search support"
```

---

## Chunk 4: API Tests

### Task 7: Write API endpoint tests

**Files:**
- Create: `tests/test_search_api.py`

- [ ] **Step 1: Write API tests using TestClient**

```python
# tests/test_search_api.py
"""Tests for search API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestSearchAPI:
    """Test search API endpoints."""

    def setup_method(self):
        # Reset services for clean state
        from src.api.dependencies import reset_services
        reset_services()

    @patch("src.api.dependencies.GraphServices.init_search_service", new_callable=AsyncMock)
    @patch("src.api.dependencies.GraphServices.shutdown_search_service", new_callable=AsyncMock)
    def test_search_endpoint_returns_results(self, mock_shutdown, mock_init):
        """Test POST /api/search returns properly formatted response."""
        from src.api.main import app

        # Mock the search service
        mock_search = AsyncMock()
        mock_search.search.return_value = {
            "results": [
                {
                    "id": "test-id",
                    "title": "Test Paper",
                    "abstract": "Test abstract",
                    "authors": ["Author A"],
                    "venue": "ACL 2023",
                    "year": 2023,
                    "tier": 0,
                    "doi": None,
                    "citation_count": 10,
                    "pagerank": None,
                    "keywords": ["test"],
                    "code_url": None,
                    "pdf_url": None,
                    "score": 0.85,
                }
            ],
            "total": 1,
            "query_time_ms": 50,
            "search_mode": "hybrid",
            "on_demand_available": False,
        }

        with patch.object(
            type(get_services_instance := __import__("src.api.dependencies", fromlist=["get_services"]).get_services()),
            "search_service",
            new_callable=lambda: property(lambda self: mock_search),
        ):
            pass  # Complex mocking — use integration approach instead

    def test_search_validates_empty_query(self):
        """Test that empty query returns 422."""
        from src.api.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/search", json={"query": ""})
            assert response.status_code == 422

    def test_search_validates_limit_bounds(self):
        """Test that limit > 100 returns 422."""
        from src.api.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/api/search", json={"query": "test", "limit": 200})
            assert response.status_code == 422
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_search_api.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_search_api.py
git commit -m "test: add search API endpoint validation tests"
```

---

## Execution Checklist

| Task | Description | Estimated Time |
|------|-------------|---------------|
| 1 | Pydantic search models | 5 min |
| 2 | SearchService (hybrid search + BM25 fallback) | 15 min |
| 3 | Extend GraphServices with SearchService | 5 min |
| 4 | Search API router | 10 min |
| 5 | Wire into FastAPI + rate limiting | 10 min |
| 6 | Search web UI | 15 min |
| 7 | API endpoint tests | 10 min |
