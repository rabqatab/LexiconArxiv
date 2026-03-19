# Phase 6: Semantic Similarity Graph — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precompute typed semantic similarity edges between papers using section-level vectors. For each paper, find top-K nearest neighbors per section, creating a multi-relational similarity graph that complements the citation graph.

**Architecture:** Batch Qdrant vector searches (no LLM needed). For each paper, run 5 `query_points` calls on different named vectors. Store results as `similar_papers` payload field. Expose via API and integrate with graph visualization.

**Tech Stack:** Qdrant query_points (vector search), asyncio concurrency, existing QdrantStorage

**Depends on:** Section-level embeddings (Phase 1 redesign) must be complete before running.

---

## Edge Types

| Edge Type | Source Vector | Target Vector | Meaning |
|---|---|---|---|
| `same_method` | section-method | section-method | Uses similar technique |
| `same_task` | section-task | section-task | Tackles same problem |
| `same_result` | section-result | section-result | Achieves similar outcome |
| `method_transfer` | section-method | section-result | A's method → B's result (extension potential) |
| `overall` | structured-abstract | structured-abstract | General section-aware similarity |

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/analytics/similarity.py` | Precompute similarity graph |
| Create | `src/cli/commands/similarity.py` | CLI command `compute-similarity` |
| Create | `scripts/analytics/run_similarity.sh` | Shell script |
| Modify | `src/api/routes/search.py` | Add GET /api/paper/{id}/similar endpoint |
| Modify | `src/api/routes/graph.py` | Add similarity edges to subgraph response |
| Create | `tests/test_similarity.py` | Tests |

---

## Task 1: Create similarity computation module

**Files:** `src/core/analytics/similarity.py`

Core function: for each non-stub paper that has section vectors, query Qdrant for top-K neighbors on each edge type.

```python
EDGE_TYPES = {
    "same_method": ("section-method", "section-method"),
    "same_task": ("section-task", "section-task"),
    "same_result": ("section-result", "section-result"),
    "method_transfer": ("section-method", "section-result"),
    "overall": ("structured-abstract", "structured-abstract"),
}

async def compute_similarity_for_paper(
    client, collection, paper_id, paper_vectors, k=10
) -> dict:
    """Find top-K similar papers per edge type."""
    results = {}
    for edge_type, (source_vec, target_vec) in EDGE_TYPES.items():
        query_vector = paper_vectors.get(source_vec)
        if not query_vector:
            continue
        search_results = client.query_points(
            collection_name=collection,
            query=query_vector,
            using=target_vec,
            query_filter=Filter(must_not=[
                FieldCondition(key="is_stub", match=MatchValue(value=True)),
                HasIdCondition(has_id=[paper_id]),  # exclude self
            ]),
            limit=k,
            with_payload=["title", "venue", "year"],
        )
        results[edge_type] = [
            {"id": str(p.id), "score": round(p.score, 4),
             "title": p.payload.get("title", "")}
            for p in search_results.points
        ]
    return results

async def compute_similarity_batch(storage, batch_size=100, k=10, concurrency=8):
    """Compute similarity for all papers in batches."""
    # Scroll papers that have section vectors
    # For each batch, retrieve vectors, run similarity queries
    # Store results as similar_papers payload
```

Key implementation details:
- Scroll non-stub papers that have the `structured-abstract` vector (HasVectorCondition)
- For each paper, retrieve its vectors (need with_vectors for the source vectors)
- Run 5 query_points calls per paper
- Use asyncio.Semaphore for concurrency (Qdrant handles parallel reads well)
- Store results via set_payload("similar_papers", results)
- Checkpoint by tracking processed paper IDs

---

## Task 2: CLI command + shell script

`compute-similarity` command with:
- `--k` (default 10) — neighbors per edge type
- `--batch-size` (default 50) — papers per batch
- `--concurrency` (default 8) — parallel Qdrant queries
- `--edge-types` (default all) — which edge types to compute
- `--dry-run` — count eligible papers

---

## Task 3: API endpoints

`GET /api/paper/{id}/similar` — returns precomputed similarity edges
`GET /api/paper/{id}/similar?type=same_method` — filter by edge type

Response:
```json
{
  "paper_id": "uuid",
  "similar_papers": {
    "same_method": [{"id": "...", "score": 0.92, "title": "..."}],
    "same_task": [...],
    "same_result": [...],
    "method_transfer": [...],
    "overall": [...]
  }
}
```

---

## Task 4: Graph visualization integration

Add similarity edges to the D3.js subgraph visualization as a new edge type:
- Dashed lines (vs solid for citation edges)
- Color by similarity type (green=method, blue=task, purple=result)
- Toggle visibility per type
- Optional: show on the search UI paper detail panel

---

## Performance Estimates

- 5 Qdrant searches per paper × ~20ms each = ~100ms per paper
- 120K papers at concurrency=8 = ~25 min
- Storage: ~5 edge types × 10 neighbors × ~50 bytes = ~500 bytes per paper = ~60 MB total
