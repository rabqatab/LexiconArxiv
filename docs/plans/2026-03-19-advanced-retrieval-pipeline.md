# Advanced Retrieval Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the search service into a configurable multi-stage retrieval pipeline where each technique can be toggled on/off via API parameters and server-side defaults.

**Architecture:** Pipeline-based search with stages: Query Analysis → Retrieval → Fusion → Reranking → Post-processing. Each stage is a pluggable component with an on/off switch.

---

## Design: Configurable Retrieval Pipeline

### Pipeline Stages

```
Query ──→ [1. Query Analysis] ──→ [2. Retrieval] ──→ [3. Fusion] ──→ [4. Reranking] ──→ [5. Post-processing] ──→ Results
              │                         │                  │                │                    │
              ├─ intent detection       ├─ multi-vector    ├─ RRF          ├─ cross-encoder     ├─ citation boost
              ├─ section routing        ├─ BM25            │               │  (Qwen3-Reranker)  ├─ MMR diversity
              ├─ HyDE expansion         │                  │               │                    ├─ venue normalize
              ├─ RAG-Fusion variants    │                  │               │                    │
              └─ query decomposition    │                  │               │                    │
```

### Configuration Model

```python
@dataclass
class RetrievalConfig:
    """Toggle each retrieval technique on/off."""

    # Stage 1: Query Analysis
    query_intent: bool = True         # Auto-detect section target from query
    hyde: bool = False                # Generate hypothetical document (adds ~500ms)
    rag_fusion: bool = False          # Generate query variants (adds ~500ms)
    query_decomposition: bool = False  # Decompose complex queries (adds ~500ms)

    # Stage 2: Retrieval
    multi_vector: bool = True         # Search multiple section vectors
    multi_vector_names: list[str] = field(default_factory=lambda: [
        "structured-abstract", "section-method", "section-task"
    ])

    # Stage 3: Fusion
    # RRF is always on (it's the base)

    # Stage 4: Reranking
    reranker: bool = False            # Cross-encoder reranking (adds ~200-500ms)
    reranker_model: str = "dengcao/Qwen3-Reranker-8B"
    rerank_top_k: int = 50           # Retrieve this many, rerank to limit

    # Stage 5: Post-processing
    citation_boost: bool = True       # Boost by citation count + pagerank
    citation_boost_alpha: float = 0.8 # Weight for retrieval score
    citation_boost_beta: float = 0.1  # Weight for log(citations)
    citation_boost_gamma: float = 0.1 # Weight for pagerank
    mmr_diversity: bool = False       # MMR result diversification
    mmr_lambda: float = 0.7          # Relevance vs diversity tradeoff
    venue_normalize: bool = True      # Normalize venue names for filtering
```

### API Interface

The search request gains an optional `retrieval` field:

```json
POST /api/search
{
    "query": "contrastive learning for NLP",
    "filters": {"year_min": 2022},
    "limit": 20,
    "retrieval": {
        "hyde": true,
        "multi_vector": true,
        "reranker": true,
        "citation_boost": true,
        "mmr_diversity": true
    }
}
```

If `retrieval` is omitted, server defaults apply. This lets the UI expose toggles and lets power users (MCP/API) fine-tune their search.

### Response Enhancement

```json
{
    "results": [...],
    "total": 156,
    "query_time_ms": 450,
    "search_mode": "hybrid",
    "pipeline": {
        "stages_applied": ["query_intent", "multi_vector", "rrf", "reranker", "citation_boost"],
        "query_analysis": {
            "detected_section": "method",
            "expanded_query": "contrastive learning self-supervised representation...",
            "hyde_generated": true
        },
        "vectors_searched": ["structured-abstract", "section-method", "section-task", "bm25"],
        "reranked": true,
        "rerank_model": "Qwen3-Reranker-8B"
    }
}
```

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/search/config.py` | RetrievalConfig dataclass + defaults |
| Create | `src/core/search/query_analyzer.py` | Stage 1: intent detection, HyDE, RAG-Fusion, decomposition |
| Create | `src/core/search/reranker.py` | Stage 4: cross-encoder reranking via Ollama |
| Create | `src/core/search/postprocess.py` | Stage 5: citation boost, MMR, venue normalization |
| Rewrite | `src/core/search/service.py` | Pipeline orchestrator using config + stages |
| Modify | `src/api/models/search.py` | Add RetrievalOptions to SearchRequest, pipeline info to response |
| Modify | `src/api/routes/search.py` | Pass retrieval config through |
| Modify | `src/mcp/server.py` | Add retrieval options to MCP search tool |
| Modify | `src/core/constants.py` | Add reranker model constant |
| Create | `tests/test_retrieval_pipeline.py` | Tests for each stage |

---

## Task 1: RetrievalConfig + constants

**Files:** `src/core/search/config.py`, `src/core/constants.py`

Create the configuration dataclass with all toggles and sensible defaults. Add reranker model constant to constants.py.

```python
# src/core/search/config.py
from dataclasses import dataclass, field

@dataclass
class RetrievalConfig:
    # Stage 1: Query Analysis
    query_intent: bool = True
    hyde: bool = False
    rag_fusion: bool = False
    query_decomposition: bool = False

    # Stage 2: Multi-vector retrieval
    multi_vector: bool = True
    multi_vector_names: list[str] = field(default_factory=lambda: [
        "structured-abstract", "section-method", "section-task",
    ])

    # Stage 4: Reranking
    reranker: bool = False
    reranker_model: str = "dengcao/Qwen3-Reranker-8B"
    rerank_top_k: int = 50

    # Stage 5: Post-processing
    citation_boost: bool = True
    citation_alpha: float = 0.8
    citation_beta: float = 0.1
    citation_gamma: float = 0.1
    mmr_diversity: bool = False
    mmr_lambda: float = 0.7
    venue_normalize: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "RetrievalConfig":
        """Create from API request dict, using defaults for missing fields."""
        if not d:
            return cls()
        valid_fields = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid_fields})
```

---

## Task 2: Query Analyzer (Stage 1)

**Files:** `src/core/search/query_analyzer.py`

Four sub-components, each independently toggleable:

### 2a. Intent detection (keyword heuristics + optional LLM)
```python
def detect_intent(query: str) -> dict:
    """Analyze query to determine target section and search strategy.

    Returns: {
        "target_section": "method" | "task" | "result" | None,
        "is_title_search": bool,
        "recency_bias": bool,
        "acronyms": ["RAG", "BERT"],
    }
    """
    # Keyword heuristics (fast, no LLM):
    # "papers using X" / "methods for X" / "how to X" → section=method
    # "papers about X" / "what is X" / "problem of X" → section=task
    # "results of X" / "performance of X" / "achieves X" → section=result
    # "latest X" / "recent X" / "2024 X" → recency_bias=True
    # Quoted strings or known paper titles → is_title_search=True
```

### 2b. HyDE (hypothetical document generation)
```python
async def generate_hyde(query: str, client: httpx.AsyncClient, base_url: str) -> str | None:
    """Use Ollama chat model to generate a hypothetical abstract.

    Prompt: "Write a short academic abstract for a paper about: {query}"
    Returns the generated text, or None on failure.
    """
```

### 2c. RAG-Fusion (multi-query generation)
```python
async def generate_query_variants(query: str, client: httpx.AsyncClient, base_url: str, n: int = 3) -> list[str]:
    """Generate N query reformulations via LLM.

    Prompt: "Generate 3 different search queries for finding academic papers about: {query}"
    Returns list of variant queries.
    """
```

### 2d. Query decomposition
```python
async def decompose_query(query: str, client: httpx.AsyncClient, base_url: str) -> list[dict]:
    """Decompose complex query into sub-queries with section targets.

    Input: "papers comparing BERT and GPT for code generation"
    Output: [
        {"query": "BERT for code generation", "section": "method"},
        {"query": "GPT for code generation", "section": "method"},
        {"query": "comparison of language models", "section": "task"},
    ]
    """
```

---

## Task 3: Multi-vector Retrieval (Stage 2)

**Files:** modify `src/core/search/service.py`

Change the current single-vector prefetch to multi-vector:

```python
# Current: 1 dense + 1 BM25 = 2 prefetch queries
prefetch = [
    Prefetch(query=vec, using="structured-abstract", ...),
    Prefetch(query=bm25_doc, using="bm25", ...),
]

# New: N dense + 1 BM25 = N+1 prefetch queries
prefetch = []
for vec_name in config.multi_vector_names:
    prefetch.append(Prefetch(query=vec, using=vec_name, ...))
prefetch.append(Prefetch(query=bm25_doc, using="bm25", ...))
# Qdrant RRF fuses all N+1 lists
```

This is the simplest high-impact change — Qdrant's `query_points` already supports multiple prefetch queries with RRF fusion.

---

## Task 4: Cross-Encoder Reranker (Stage 4)

**Files:** `src/core/search/reranker.py`

```python
class CrossEncoderReranker:
    """Rerank search results using Qwen3-Reranker via Ollama."""

    def __init__(self, model: str, base_url: str, timeout: float = 10.0):
        ...

    async def rerank(
        self, query: str, results: list[dict], top_k: int = 20
    ) -> list[dict]:
        """Rerank results by cross-encoder relevance score.

        For each result, sends (query, title + abstract) to the reranker model.
        Returns results sorted by reranker score.
        """
        # The Qwen3-Reranker uses a special prompt format:
        # Input: query + document → relevance score
        # Implementation depends on Ollama's reranker API
        # May need to use /api/generate with a ranking prompt
```

Note: Need to verify how Qwen3-Reranker works via Ollama. It may use `/api/embed` with a different prompt format, or require a custom scoring approach.

---

## Task 5: Post-processing (Stage 5)

**Files:** `src/core/search/postprocess.py`

### 5a. Citation-aware score boosting
```python
def apply_citation_boost(
    results: list[dict],
    alpha: float = 0.8,  # retrieval score weight
    beta: float = 0.1,   # citation weight
    gamma: float = 0.1,  # pagerank weight
) -> list[dict]:
    """Boost scores using citation signals."""
    import math
    for r in results:
        retrieval = r["score"]
        citations = math.log(1 + r.get("citation_count", 0))
        max_citations = max(math.log(1 + r.get("citation_count", 0)) for r in results) or 1
        pagerank = r.get("pagerank") or 0

        r["score"] = (
            alpha * retrieval
            + beta * (citations / max_citations)
            + gamma * min(pagerank * 100, 1.0)
        )
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
```

### 5b. MMR diversity
```python
def apply_mmr(
    results: list[dict],
    vectors: list[list[float]],  # result vectors for similarity
    lambda_param: float = 0.7,
    limit: int = 20,
) -> list[dict]:
    """Maximal Marginal Relevance for result diversification."""
    # Iteratively select results that balance relevance and diversity
    selected = []
    remaining = list(range(len(results)))

    while len(selected) < limit and remaining:
        best_idx = None
        best_score = -float('inf')

        for idx in remaining:
            relevance = results[idx]["score"]
            max_sim = max(
                cosine_similarity(vectors[idx], vectors[s])
                for s in selected
            ) if selected else 0

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        selected.append(best_idx)
        remaining.remove(best_idx)

    return [results[i] for i in selected]
```

### 5c. Venue name normalization
```python
# Mapping of common venue name patterns to canonical short names
VENUE_ALIASES = {
    "neurips": ["NeurIPS", "Neural Information Processing Systems", "NeurIPS 20"],
    "icml": ["ICML", "International Conference on Machine Learning", "ICML 20"],
    "iclr": ["ICLR", "International Conference on Learning Representations", "ICLR 20"],
    "acl": ["ACL", "Annual Meeting of the Association for Computational Linguistics"],
    "emnlp": ["EMNLP", "Empirical Methods in Natural Language Processing"],
    # ... etc
}

def normalize_venue_filter(venues: list[str]) -> list[str]:
    """Expand short venue names to match all Qdrant venue variations."""
    # "ICLR" → ["ICLR 2025 Poster", "ICLR 2024 poster", "ICLR 2023 notable top 25%", ...]
```

For venue normalization, instead of expanding at query time (fragile), we could:
- Add a `venue_canonical` payload field during enrichment (e.g., "ICLR" regardless of "ICLR 2024 poster")
- Or use Qdrant's MatchText (substring filter) instead of MatchAny (exact)

The payload field approach is cleaner — add `venue_canonical` during collection.

---

## Task 6: Rewrite SearchService as pipeline

**Files:** `src/core/search/service.py`

The main `search()` method becomes a pipeline orchestrator:

```python
async def search(self, query, filters, section, limit, offset, config: RetrievalConfig | None = None):
    cfg = config or RetrievalConfig()
    start = time.time()
    pipeline_info = {"stages_applied": []}

    # ── Stage 1: Query Analysis ──
    analyzed = {"queries": [query], "section": section}

    if cfg.query_intent and not section:
        intent = detect_intent(query)
        analyzed["section"] = intent.get("target_section")
        pipeline_info["query_analysis"] = intent
        pipeline_info["stages_applied"].append("query_intent")

    if cfg.hyde:
        hyde_text = await generate_hyde(query, self._client, self._base_url)
        if hyde_text:
            analyzed["queries"].append(hyde_text)
            pipeline_info["stages_applied"].append("hyde")

    if cfg.rag_fusion:
        variants = await generate_query_variants(query, self._client, self._base_url)
        analyzed["queries"].extend(variants)
        pipeline_info["stages_applied"].append("rag_fusion")

    # ── Stage 2: Retrieval ──
    retrieve_limit = cfg.rerank_top_k if cfg.reranker else (limit + offset)

    # Embed all queries
    all_vectors = []
    for q in analyzed["queries"]:
        vec = await self._embed_query(q)
        if vec:
            all_vectors.append(vec)

    # Build prefetch: multi-vector × multi-query × BM25
    prefetch = []
    vec_names = cfg.multi_vector_names if cfg.multi_vector else ["structured-abstract"]

    for vec in all_vectors:
        for vec_name in vec_names:
            prefetch.append(Prefetch(query=vec, using=vec_name, filter=qdrant_filter, limit=retrieve_limit))

    # BM25 for each query variant
    for q in analyzed["queries"]:
        prefetch.append(Prefetch(query=Document(text=q, model="qdrant/bm25"), using="bm25", filter=qdrant_filter, limit=retrieve_limit))

    pipeline_info["vectors_searched"] = vec_names + ["bm25"]
    pipeline_info["stages_applied"].append("multi_vector" if cfg.multi_vector else "single_vector")

    # ── Stage 3: Fusion (RRF) ──
    results = self._storage.client.query_points(
        collection_name=...,
        prefetch=prefetch,
        query=FusionQuery(fusion=Fusion.RRF),
        limit=retrieve_limit,
        with_payload=True,
    )
    pipeline_info["stages_applied"].append("rrf")

    # Format results
    items = [self._format_result(p) for p in results.points]

    # ── Stage 4: Reranking ──
    if cfg.reranker and self._reranker:
        items = await self._reranker.rerank(query, items, top_k=limit + offset)
        pipeline_info["stages_applied"].append("reranker")

    # ── Stage 5: Post-processing ──
    if cfg.citation_boost:
        items = apply_citation_boost(items, cfg.citation_alpha, cfg.citation_beta, cfg.citation_gamma)
        pipeline_info["stages_applied"].append("citation_boost")

    if cfg.mmr_diversity:
        # Need vectors for MMR — retrieve from results
        items = apply_mmr(items, lambda_param=cfg.mmr_lambda, limit=limit + offset)
        pipeline_info["stages_applied"].append("mmr_diversity")

    # Apply offset
    items = items[offset:offset + limit]

    return {
        "results": items,
        "total": total,
        "query_time_ms": elapsed,
        "search_mode": search_mode,
        "pipeline": pipeline_info,
    }
```

---

## Task 7: Update API models and routes

**Files:** `src/api/models/search.py`, `src/api/routes/search.py`

Add `RetrievalOptions` to SearchRequest:
```python
class RetrievalOptions(BaseModel):
    query_intent: bool | None = None
    hyde: bool | None = None
    rag_fusion: bool | None = None
    query_decomposition: bool | None = None
    multi_vector: bool | None = None
    reranker: bool | None = None
    citation_boost: bool | None = None
    mmr_diversity: bool | None = None

class SearchRequest(BaseModel):
    query: str = Field(...)
    filters: SearchFilters | None = None
    section: str | None = None
    retrieval: RetrievalOptions | None = None
    limit: int = Field(default=20)
    offset: int = Field(default=0)
```

Add `PipelineInfo` to SearchResponse:
```python
class PipelineInfo(BaseModel):
    stages_applied: list[str]
    query_analysis: dict | None = None
    vectors_searched: list[str] = []
    reranked: bool = False

class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    query_time_ms: int
    search_mode: str
    pipeline: PipelineInfo | None = None
```

---

## Task 8: Update MCP search tool

Add retrieval options to the MCP `search_papers` tool schema.

---

## Task 9: Venue normalization data

**Files:** `src/core/search/postprocess.py`

Build the venue alias mapping. Two approaches:
1. **Runtime**: query-time expansion of short names to all matching Qdrant venue strings
2. **Index-time**: add `venue_canonical` field during collection (preferred but requires re-enrichment)

For now: runtime approach using substring matching in Qdrant. Instead of `MatchAny(any=["ICLR"])`, use `MatchText(text="ICLR")` which does substring matching.

Wait — Qdrant's `MatchText` requires a full-text index. Alternative: scroll unique venue names at startup, build a mapping, and expand at query time.

---

## Task 10: Tests

Test each stage independently:
- Query intent detection (keyword heuristics)
- Citation boost formula
- MMR selection
- Multi-vector prefetch produces more prefetch queries
- Pipeline config toggles work correctly
- Venue normalization expands correctly

---

## Execution Order

| Task | Description | Depends On | Est. Time |
|------|-------------|------------|-----------|
| 1 | RetrievalConfig + constants | Nothing | 5 min |
| 2 | Query analyzer (intent + HyDE + RAG-Fusion + decomposition) | 1 | 20 min |
| 3 | Multi-vector retrieval | 1 | 10 min |
| 4 | Cross-encoder reranker | 1 | 15 min |
| 5 | Post-processing (citation boost + MMR + venue normalize) | 1 | 15 min |
| 6 | Rewrite SearchService as pipeline | 1-5 | 20 min |
| 7 | Update API models + routes | 6 | 10 min |
| 8 | Update MCP tool | 6 | 5 min |
| 9 | Venue normalization data | 5 | 10 min |
| 10 | Tests | All | 15 min |

---

## Default Configurations

### "Fast" preset (default for API)
```python
RetrievalConfig(
    query_intent=True,
    multi_vector=True,
    citation_boost=True,
    venue_normalize=True,
    # Everything else off
)
```

### "Quality" preset (for MCP/power users)
```python
RetrievalConfig(
    query_intent=True,
    hyde=True,
    multi_vector=True,
    reranker=True,
    citation_boost=True,
    mmr_diversity=True,
    venue_normalize=True,
)
```

### "Comprehensive" preset (for research/exploration)
```python
RetrievalConfig(
    query_intent=True,
    rag_fusion=True,
    multi_vector=True,
    reranker=True,
    citation_boost=True,
    mmr_diversity=True,
    venue_normalize=True,
)
```
