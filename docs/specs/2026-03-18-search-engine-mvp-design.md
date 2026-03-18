# Search Engine MVP Design (Phase 1 through Phase 5)

> Full-stack search, MCP integration, on-demand retrieval, and trend analytics for LexiconArxiv.

**Date:** 2026-03-18
**Status:** Approved

---

## 1. Context

LexiconArxiv has a mature data pipeline producing 145K core papers and 1.7M stubs in Qdrant (payload-only, 0 vectors). The enrichment pipeline is complete: 97% abstracts, 98% referenced works, 75% resolved references, ~80% keywords and abstract labeling, code repositories on 62K papers.

The missing layer is search, discovery, and user-facing access. This spec covers the full path from embedding generation through trend analytics, organized in five phases.

### MVP mapping

| MVP | Phases | Milestone |
|-----|--------|-----------|
| **MVP-1** | Phase 1 + 2 | Core corpus is searchable (hybrid search + web UI) |
| **MVP-2** | Phase 3 + 4 | Agent integration + on-demand expansion beyond core |
| **MVP-3** | Phase 5 | Trend analysis and notable paper discovery |

### Current state

| Metric | Value |
|--------|-------|
| Total Qdrant points | 1,877,102 |
| Core papers | 145,494 |
| Stub papers | 1,731,608 |
| Indexed vectors | 0 |
| Papers with abstracts | 141,238 (97%) |
| Papers with keywords | 114,275 |
| Papers with abstract_structure | 116,220 |
| Papers with resolved_references | 108,433 |
| Papers with code_repositories | 62,439 |

### Hardware

NVIDIA DGX Spark (GB10 Superchip) — Grace Blackwell, 128 GB unified memory. More than sufficient for all inference workloads described here.

---

## 2. Phase Overview

| Phase | Deliverable | Depends On |
|-------|-------------|------------|
| 1 | Embedding Pipeline | Nothing |
| 2 | Search API + Web UI | Phase 1 |
| 3 | MCP Server | Phase 2 |
| 4 | On-demand Retrieval | Phase 2 |
| 5 | Trends & Notable Papers | Phase 1 + 2 |

---

## 3. Phase 1: Embedding Pipeline

### 3.1 Model

- **Model:** Qwen3-Embedding-8B
- **Runtime:** Ollama (`qwen3-embedding:8b`)
- **Dimensions:** 1024 via Matryoshka Representation Learning (truncated from 4096)
- **Max tokens:** 32,768 (abstracts use <500)
- **Instruction prefix:** `"Retrieve academic papers: {abstract}"` (Qwen3 is instruction-aware)

### 3.2 Qdrant collection migration

The existing `lexicon_arxiv` collection was created with `vectors_config={}` (payload-only). Qdrant does not support adding new named vector configs to an existing collection via `update_collection()`. A **collection migration** is required:

1. **Snapshot backup:** Create a Qdrant snapshot of the existing collection via `POST /collections/lexicon_arxiv/snapshots`
2. **Create new collection** with the correct config:
   - Dense named vector: `"abstract-qwen3-8b"` (dim=1024, cosine distance)
   - Sparse vector for BM25: `"bm25"` with `SparseVectorParams(modifier=Modifier.IDF)` — Qdrant 1.16's built-in BM25 scoring via server-side tokenization
3. **Re-insert all 1.87M points** from the old collection to the new one, preserving point IDs and payloads. Migration script scrolls old collection and batch-upserts into the new one (vectors can be empty `{}` initially — same payload-only approach, but the vector config is now ready).
4. **Delete old collection** after verification.

This migration preserves all existing data while enabling both dense and sparse vector search. The migration script is a one-time operation (~10-15 minutes for 1.87M points).

**BM25 approach:** Qdrant 1.16 supports server-side BM25 via the `qdrant/bm25` inference model. At upsert time, pass `Document(text=abstract, model="qdrant/bm25")` as the sparse vector — Qdrant tokenizes and stores it automatically. At query time, pass `Document(text=query, model="qdrant/bm25")` — Qdrant scores using BM25 with IDF. No client-side tokenization needed. This participates in RRF fusion natively.

### 3.3 Vector upload

- Dense + sparse vectors are upserted together in a single `client.upsert()` call per batch:
  - Dense: Qwen3-8B embedding (1024d, truncated client-side from 4096d via MRL)
  - Sparse: `models.Document(text=abstract, model="qdrant/bm25")` — server-side BM25 tokenization
- Ollama's `/api/embed` returns full 4096d output — **client-side truncation to the first 1024 dimensions** is required (Ollama does not support MRL truncation natively). This is valid because Qwen3-Embedding was trained with Matryoshka Representation Learning.

### 3.4 Batch embedding

- New module: `src/core/embedding/embedder.py`
- Async batch embedding via `httpx` POST to Ollama `/api/embed` endpoint (consistent with existing Ollama usage in `src/core/keyword/ollama.py` and `src/core/labeling/ollama.py` — no `ollama` Python SDK)
- Dense vectors: Qwen3-8B via Ollama, truncate 4096d → 1024d client-side
- Sparse vectors: Qdrant server-side BM25 via `Document(text=abstract, model="qdrant/bm25")` — no client-side tokenization
- Batch size: 32-64 abstracts per request
- Concurrency: multiple parallel Ollama requests via `asyncio.gather`
- Checkpoint/resume: track embedded paper IDs in file-based checkpoint (existing pattern)
- Only embed papers with non-empty abstracts (141K of 145K)

### 3.5 CLI + script

- New CLI command: `embed-papers` with `--batch-size`, `--concurrency`, `--resume` flags
- New script: `scripts/embedding/run_embedding.sh`

### 3.6 Performance estimates

- Throughput: ~50-100 abstracts/second on GB10
- Total time: ~25-50 minutes for 145K papers (embedding), ~10-15 minutes for migration (1.87M point re-insert)
- Storage: ~594 MB raw dense vector data at 1024d float32 (~900 MB–1.2 GB total with HNSW index overhead and sparse vectors). Stub points without vectors add minimal metadata overhead.

---

## 4. Phase 2: Search API + Web UI

### 4.1 Search endpoint

**`POST /api/search`**

Request:
```json
{
  "query": "retrieval augmented generation",
  "filters": {
    "venues": ["ACL", "EMNLP"],
    "year_min": 2022,
    "year_max": 2025,
    "tiers": [0, 1]
  },
  "limit": 20,
  "offset": 0
}
```

Response:
```json
{
  "results": [
    {
      "id": "uuid",
      "title": "...",
      "abstract": "...",
      "authors": ["..."],
      "venue": "ACL 2023",
      "year": 2023,
      "tier": 0,
      "doi": "...",
      "citation_count": 142,
      "pagerank": 0.0023,
      "keywords": ["RAG", "retrieval"],
      "code_url": "https://github.com/...",
      "pdf_url": "...",
      "score": 0.87,
      "score_breakdown": {"dense": 0.82, "bm25": 0.91}
    }
  ],
  "total": 156,
  "query_time_ms": 120,
  "search_mode": "hybrid",
  "on_demand_available": true
}
```

### 4.2 Additional endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/search/suggest?q={prefix}&limit=10` | Autocomplete: returns keyword suggestions matching prefix. Backed by an in-memory prefix trie built from all `keywords` values at startup. Target: <50ms. |
| `GET /api/paper/{id}` | Full paper detail + citation graph neighbors. Extends existing `/graph/paper/{paper_id}` with richer metadata (keywords, abstract_structure, code_repos). |
| `GET /api/paper/{id}/references?limit=20&offset=0` | Paginated papers this paper cites (resolved_references with metadata) |
| `GET /api/paper/{id}/cited-by?limit=20&offset=0` | Paginated papers citing this one (cited_by with metadata) |
| `GET /api/stats` | Corpus stats |

### 4.3 Search orchestration

1. Embed user query via `httpx` to Ollama `/api/embed` (Qwen3-8B, truncate to 1024d) — ~50-100ms
2. Qdrant hybrid search via `query_points` with `prefetch`:
   - Dense sub-query: query vector on named vector `"abstract-qwen3-8b"` (cosine similarity)
   - Sparse sub-query: `Document(text=query, model="qdrant/bm25")` on `"bm25"` (server-side BM25 scoring)
3. Fusion: `FusionQuery(fusion=Fusion.RRF)`
4. Apply payload filters (venue, year, tier)
5. Return ranked results with score breakdown

Target latency: <2 seconds P95 (per PRD).

**Note on `total` field:** The `total` in search response is the count of papers matching the payload filters (venue/year/tier), obtained via a separate `client.count()` call. It represents the filtered corpus size, not a relevance-based count.

**Note on `on_demand_available`:** This flag is `true` when the server is configured with arXiv/OpenAlex API access (Phase 4 deployed). `false` before Phase 4 or when external APIs are rate-limited/unreachable.

### 4.4 Implementation

- Extend existing `src/api/main.py` (already has graph routes)
- New router: `src/api/routes/search.py`
- New models: `src/api/models/search.py`
- New service: `src/core/search/service.py` (orchestrates embedding + Qdrant query)
- **Service wiring:** Extend `GraphServices` in `src/api/dependencies.py` with `_search_service: SearchService | None = None`. Add an `async def init_search_service()` method called from the existing `lifespan` async context manager in `main.py` — this creates the `httpx.AsyncClient` for Ollama (which requires an event loop). Cleanup of the async client happens in the lifespan's shutdown phase. The `SearchService` reuses the existing `QdrantStorage` instance.

### 4.4.1 Ollama failure handling

- **Startup:** Health check via `GET /api/tags` — verify Ollama is reachable AND `qwen3-embedding:8b` appears in the model list. Log warning if unavailable but allow API to start.
- **Query time:** 5-second timeout on query embedding. If Ollama is down or times out, fall back to BM25-only search via `Document(text=query, model="qdrant/bm25")` on the `"bm25"` vector (degraded but functional — Qdrant handles tokenization server-side, no LLM needed). Response includes `"search_mode": "hybrid"` or `"search_mode": "bm25_only"` to indicate which mode was used.

### 4.5 Web UI

Minimal single-page search interface at `src/api/static/search.html`:

- Search bar with query input + filter dropdowns (venue, year range, tier)
- Results list: title, authors, venue/year, abstract snippet, citation count, keyword tags, code repo link
- Paper detail panel: full abstract with rhetorical labels (from `abstract_structure`), references, cited-by, link to graph viz
- Score breakdown indicator (dense vs BM25 contribution)
- Technology: vanilla HTML/CSS/JS (matches existing D3.js static file pattern, no build step)

### 4.6 Rate limiting

- Open access, no authentication
- Rate limit by IP: 60 requests/minute for search, 120/minute for reads
- Implemented via FastAPI middleware (e.g., `slowapi`)

---

## 5. Phase 3: MCP Server

### 5.1 Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_papers` | `query`, `filters`, `limit` | Hybrid search over corpus |
| `get_paper` | `identifier` (ID, DOI, or arXiv ID) | Full paper detail |
| `get_citations` | `paper_id`, `direction` (refs/cited_by/both), `depth` (1-3) | Citation graph neighbors |
| `get_corpus_stats` | none | Corpus coverage stats |
| `expand_search` | `query`, `sources` (arxiv/openalex/both) | On-demand expansion (Phase 4) |

### 5.2 Architecture

- MCP server is a thin transport wrapper over the shared service layer
- Same `src/core/search/` and `src/core/storage/` used by REST API
- No logic duplication between API and MCP

### 5.3 Response format

Tools return pre-formatted, LLM-friendly text (not raw JSON) to minimize token usage:

```
Found 20 results (156 total). Top 5:

1. "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
   Lewis et al. · NeurIPS 2020 · Tier 0 · 3,421 citations
   Keywords: RAG, retrieval, knowledge-intensive, seq2seq
   Score: 0.94 (dense: 0.91, bm25: 0.97)
```

### 5.4 Implementation

- New module: `src/mcp/server.py` using the `mcp` Python SDK
- Entry point: `uv run python -m src.mcp.server`
- Configurable via `claude_desktop_config.json` or Claude Code MCP settings

---

## 6. Phase 4: On-demand Retrieval

### 6.1 Trigger

- REST API: `POST /api/search/expand` (separate endpoint)
- Web UI: "Expand to arXiv & OpenAlex" button below core results
- MCP: `expand_search` tool

User-triggered only — no automatic external queries.

### 6.2 Sources

| Source | API | Rate Limit | Coverage |
|--------|-----|-----------|----------|
| arXiv | Atom feed (`export.arxiv.org/api/query`) | 1 req/3s | Preprints |
| OpenAlex | Works endpoint (multi-key) | 100K/day/key | Published papers |

### 6.3 Data flow

1. Query arXiv + OpenAlex in parallel
2. Normalize to common schema
3. Deduplicate against core corpus (DOI / arXiv ID / title match)
4. Label each result:
   - `"core"` — already in corpus
   - `"connected"` — cites or is cited by core papers
   - `"external"` — no core connection
5. Merge with core results, return unified ranked list

### 6.4 Connection detection

For each external result:
1. DOI/arXiv ID match against Qdrant → "core"
2. Check external paper's references against core DOIs → "connected" (cites core)
3. Check stub index for external paper's DOI → "connected" (cited by core)
4. No match → "external"

### 6.5 Caching

- In-memory LRU cache with TTL via `cachetools.TTLCache`, guarded by `asyncio.Lock` for async concurrency safety
- 24-hour TTL, max 1000 cached queries
- No permanent storage of external papers (ephemeral by design)

### 6.6 Response schema

```json
{
  "core_results": [...],
  "expanded_results": [
    {
      "title": "...",
      "authors": [...],
      "source": "arxiv",
      "arxiv_id": "2603.12345",
      "abstract": "...",
      "connection": "connected",
      "connected_papers": [
        {"id": "uuid", "title": "...", "relation": "cites"}
      ]
    }
  ],
  "expansion_stats": {
    "arxiv_fetched": 25,
    "openalex_fetched": 40,
    "deduplicated": 12,
    "connected": 18,
    "external": 35
  }
}
```

### 6.7 Implementation

- New module: `src/core/search/on_demand.py`
- New arXiv client: `src/core/search/arxiv_client.py`
- Reuses existing OpenAlex key management from `src/core/constants.py`
- Connection detection reuses `QdrantStorage.queries` and stub index

---

## 7. Phase 5: Trends & Notable Papers

### 7.1 Layer 1: Metrics-based

**Notable paper scoring:**
```
notable_score = w1 * norm(citation_count)
              + w2 * norm(pagerank)
              + w3 * recency_boost(year)
              + w4 * tier_boost(tier)
```

Default weights: 0.3, 0.3, 0.2, 0.2 (tunable).

**Keyword trends:**
- Time-series keyword frequency from `keywords_structured` fields
- `keywords_structured` schema: `{"task": [str], "method": [str], "model": [str], "domain": [str], "dataset": [str], "contribution_type": [str], "modality": [str]}`
- Growth rate: `count(year_N) / count(year_N-2)`
- "Rising" keywords: top-K by growth rate above a minimum paper count threshold

### 7.2 Layer 2: Embedding clustering

**Topic discovery:**
1. Load 145K paper vectors (1024d)
2. UMAP dimensionality reduction (1024d → 50d)
3. HDBSCAN clustering (auto-discovers cluster count, labels outliers as noise)
4. Label clusters via top keywords from `keywords_structured` per cluster
5. Track cluster size by year → emerging vs declining topics

**Refresh:** Weekly or on-demand recompute (~2-5 minutes). Store `cluster_id`, `umap_x`, `umap_y` as Qdrant payload fields.

### 7.3 Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/trends/notable` | Top papers by notable score, filterable |
| `GET /api/trends/keywords` | Keyword frequency time-series |
| `GET /api/trends/rising` | Fastest-growing keywords/topics |
| `GET /api/trends/topics` | Discovered topic clusters with labels and growth |
| `GET /api/trends/topics/{id}` | Papers in a cluster |
| `GET /api/trends/map` | 2D UMAP coordinates for scatter plot visualization |

### 7.4 MCP tools

| Tool | Description |
|------|-------------|
| `get_trending_topics` | Rising keywords and topic clusters |
| `get_notable_papers` | Top papers by notable score with filters |

### 7.5 Web UI: Trends page (`/trends`)

- Rising keywords bar chart by category
- Notable papers ranked list with score breakdown
- 2D topic map scatter plot (UMAP), clusters color-coded, hover for paper titles, click to search within cluster

### 7.6 Implementation

- New module: `src/core/analytics/`
  - `notable.py` — scoring function
  - `keyword_trends.py` — time-series analysis
  - `clustering.py` — UMAP + HDBSCAN pipeline
- New routes: `src/api/routes/trends.py`
- New dependency: `umap-learn`. For HDBSCAN, use `sklearn.cluster.HDBSCAN` (available since scikit-learn 1.3) instead of the standalone `hdbscan` package to avoid Python 3.12+ compatibility issues.
- New script: `scripts/analytics/run_clustering.sh`

---

## 8. New Dependencies

| Package | Phase | Purpose |
|---------|-------|---------|
| (none — uses existing `httpx`) | 1 | Embedding via Ollama REST API |
| `slowapi` | 2 | IP-based rate limiting |
| `cachetools` | 4 | TTL cache for on-demand results |
| `mcp` | 3 | MCP server SDK |
| `scikit-learn` | 5 | HDBSCAN clustering (built-in since 1.3) |
| `umap-learn` | 5 | Dimensionality reduction |

---

## 9. New File Structure

```
src/
├── core/
│   ├── embedding/
│   │   └── embedder.py          # Phase 1
│   ├── search/
│   │   ├── service.py           # Phase 2
│   │   ├── on_demand.py         # Phase 4
│   │   └── arxiv_client.py      # Phase 4
│   └── analytics/
│       ├── notable.py           # Phase 5
│       ├── keyword_trends.py    # Phase 5
│       └── clustering.py        # Phase 5
├── api/
│   ├── routes/
│   │   ├── search.py            # Phase 2
│   │   └── trends.py            # Phase 5
│   ├── models/
│   │   └── search.py            # Phase 2
│   └── static/
│       ├── search.html          # Phase 2
│       └── trends.html          # Phase 5
└── mcp/
    └── server.py                # Phase 3

scripts/
├── embedding/
│   ├── migrate_collection.sh    # Phase 1 (one-time migration)
│   └── run_embedding.sh         # Phase 1
└── analytics/
    └── run_clustering.sh        # Phase 5
```

---

## 10. Testing Strategy

- **Embedding pipeline:** Unit tests with mock Ollama responses (existing `respx` pattern). Integration test embedding a small batch against live Ollama.
- **Search service:** Unit tests for query orchestration, filter construction, RRF fusion. Integration tests for known-good queries (e.g., "attention is all you need" should return the Transformer paper).
- **On-demand:** Mock arXiv/OpenAlex responses via `respx`. Test dedup and connection detection logic.
- **Trends:** Unit tests for notable scoring formula and keyword trend aggregation. Integration test for UMAP+HDBSCAN on a small vector subset.
- **MCP server:** Test tool handlers return well-formatted responses. Test with `mcp` client SDK.

---

## 11. Success Criteria (from PRD)

| Metric | Target | How |
|--------|--------|-----|
| Core coverage | 95%+ Tier 0 | Already met (145K papers) |
| Search latency P95 | <2 seconds | Query embed (~100ms) + Qdrant search (~50ms) |
| Graph loading P95 | <3 seconds | Already met (existing graph API) |
| Core-arXiv connection rate | >30% | On-demand connection detection (Phase 4) |
