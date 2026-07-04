# Qdrant Tuning for Mixed Read/Write Load

**When to read this:** search latency has jumped (multi-vector RRF queries taking multiple seconds or hitting the 60s "fill query context" internal timeout) while a bulk write job (labeling, embed drain, refs resolution) is running against the same collection.

**Root cause pattern:** Qdrant's default `hnsw_config.max_indexing_threads=0` and `optimizers_config.max_optimization_threads=null` are both "unlimited" — background HNSW indexing and segment-merge optimizer work will consume every available CPU core, starving user-facing search queries.

The 2026-07-04 catchup labeling job (`b2ab` then `be19`) reproduced this at ~78% baseline Qdrant CPU: multi-vector search (three concurrent HNSW queries + BM25 + RRF fusion) hit Qdrant's own 60s timeout and returned 500 errors. See [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Ollama→vLLM policy for the broader read-heavy vs write-heavy contention model.

---

## The fix

Cap both background thread pools at 2. On the GB10 (10 physical cores exposed as ~14 logical), this leaves 6–10 cores free for search. Verified 2026-07-04: multi-vector search under labeling load went from **60 s+ timeout → ~1.5–2.3 s (usable)**.

### For a fresh collection

The `QdrantStorage.ensure_collection_with_vectors()` code path (see `src/core/storage/base.py`, updated 2026-07-04) now passes these caps to `create_collection`. Nothing to do — new collections inherit the tuning.

### For an existing collection

PATCH the running collection. No restart needed; changes affect new segment work immediately (existing in-flight indexing continues to completion, then the caps kick in on the next merge).

```bash
curl -sf --max-time 30 -X PATCH \
    http://localhost:6333/collections/lexicon_arxiv_v3 \
    -H 'Content-Type: application/json' \
    -d '{
        "hnsw_config": {"max_indexing_threads": 2},
        "optimizers_config": {"max_optimization_threads": 2}
    }'
```

Expected response: `{"result": true, "status": "ok", "time": <small>}`.

### Verify the caps stuck

```bash
curl -sf http://localhost:6333/collections/lexicon_arxiv_v3 | \
    jq '{hnsw: .result.config.hnsw_config.max_indexing_threads,
         opt: .result.config.optimizer_config.max_optimization_threads}'
```

Expect `{"hnsw": 2, "opt": 2}`.

### Verify search is healthy again

```bash
uv run python -c "
import asyncio, time
from src.core.storage.base import QdrantStorage
from src.core.search.service import SearchService

async def main():
    storage = QdrantStorage()
    service = SearchService(storage=storage, query_timeout=30)
    async with service:
        for q in ['attention', 'diffusion', 'graph neural network', 'reinforcement']:
            t = time.perf_counter()
            r = await service.search(query=q, limit=10)
            elapsed = time.perf_counter() - t
            print(f'  {elapsed*1000:5.0f}ms  {q:30}  mode={r[\"search_mode\"]}')

asyncio.run(main())
"
```

Under bulk load, expect **~1.5–3 s per query**, `mode=hybrid`. Anything hitting 10 s+ or falling back to `bm25_only` means the caps aren't in effect or another job is starving Qdrant.

---

## When to revert

Only if search stops being CPU-bound and bulk-write throughput becomes the bottleneck (e.g. no active labeling/embed job, and steady-state incremental cycles want max index throughput).

To revert to Qdrant defaults:

```bash
curl -sf -X PATCH http://localhost:6333/collections/lexicon_arxiv_v3 \
    -H 'Content-Type: application/json' \
    -d '{
        "hnsw_config": {"max_indexing_threads": 0},
        "optimizers_config": {"max_optimization_threads": null}
    }'
```

## References

- Qdrant [collection config docs](https://qdrant.tech/documentation/concepts/collections/#update-collection-parameters)
- Related runbook: [`vllm-labeling.md`](vllm-labeling.md) (labeling is the biggest CPU consumer that motivated this)
- Bulk vs incremental policy: [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md)
- 2026-07-04 incident context in the v0.13.3 changelog in [`README.md`](../../README.md)
