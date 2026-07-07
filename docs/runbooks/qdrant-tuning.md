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

---

## Payload indices (added 2026-07-06)

**Symptom this fixes:** any filter on an unindexed payload field triggers a full-collection scan. On 6.2 M points this hits Qdrant's server-side 60–150 s `scroll_by_id` / `retrieve` timeout and the request comes back as a 500. Retry does not help because the second attempt is just as slow. Today's 830c / d582 / 7e38 incremental cycles all died this way — enricher filters on `abstract==""` (unindexed) or `referenced_works` (unindexed) blew past the timeout.

**How this differs from the CPU tuning above:** the CPU tuning helps when search competes with bulk-write background work. The payload indices fix a different failure mode — a single filter query going deterministically over the time budget because Qdrant has no index for the field being filtered on.

### The seven indices we added

Fields chosen by walking every scroll/count callsite in `src/core/storage/reader.py` and `src/core/enrichment/` for what the incremental pipeline actually filters on, then extended when the Wave 4b/4c cleanup planning needed `tier` and `promoted_from_stub`. All are online-buildable (no downtime).

| Field | Type | Points at build | Fixes |
|---|---|---:|---|
| `abstract_structure_source` | keyword | 240 020 | labeling backlog scans; separating Ollama-labeled vs vLLM-labeled subsets |
| `injected_from_snapshot` | bool | 2 590 221 | P2/P3 subset queries |
| `snapshot_filled_at` | datetime | 4 745 799 | P2/P3 date-bucket queries |
| `year` | integer | 4 776 714 | year-based chronological chunking of the labeling backlog |
| `type` | keyword | 4 600 242 | non-article cleanup (book / peer-review / editorial per [Wave 4b](../refactoring/2026-07-04-code-overhaul-plan.md)) |
| `promoted_from_stub` | bool | 974 457 | P2-promoted subset queries (Wave 4c topic gate) |
| `tier` | integer | 3 056 | tier-priority labeling — most points don't carry it, incremental crawler sets it only on the 178 K OpenAlex venue-crawled slice |
| `graph_indexed` | bool | 1 809 430 | Step 9 `build-cited-by --incremental` filter — before this the incremental scan was O(N) on 6.2 M points even though the update set was small |

Prior indices (fetched_at, doi, openalex_id, arxiv_id, source_id, venue, is_stub) already existed — see the collection payload_schema for the current full list.

### Add them on a collection that doesn't have them

```bash
for entry in \
    "abstract_structure_source:keyword" \
    "injected_from_snapshot:bool" \
    "snapshot_filled_at:datetime" \
    "year:integer" \
    "type:keyword" \
    "promoted_from_stub:bool" \
    "tier:integer"
do
    field="${entry%:*}"
    schema="${entry#*:}"
    echo "creating index: $field ($schema)..."
    curl -sf -X PUT --max-time 30 \
        "http://localhost:6333/collections/lexicon_arxiv_v3/index?wait=false" \
        -H 'Content-Type: application/json' \
        -d "{\"field_name\": \"$field\", \"field_schema\": \"$schema\"}"
done
```

Poll `curl http://localhost:6333/collections/lexicon_arxiv_v3 | jq .result.payload_schema` until all five appear with non-zero `points`. Typical build wall time on this collection: ~10–30 min per field, in parallel.

### Verify a previously-fatal query is now fast

```bash
uv run python -c "
import time
from src.core.storage.base import QdrantStorage
from qdrant_client.http import models

s = QdrantStorage()
# Bulk-to-label size — this was a 60 s timeout before the indices.
t = time.time()
f = models.Filter(
    must=[models.IsEmptyCondition(is_empty=models.PayloadField(key='abstract_structure_source'))],
    must_not=[models.FieldCondition(key='is_stub', match=models.MatchValue(value=True))],
)
c = s.client.count(collection_name=s.collection_name, count_filter=f, exact=True).count
print(f'{c:,} unlabeled non-stubs in {time.time()-t:.2f}s')
"
```

Expect ~0.5 s. Anything over a couple seconds means one of the new indices hasn't finished building yet — check `payload_schema[<field>].points`.

### Prevention

Any new filter shape a code path relies on should either use one of the indexed fields above OR add its own index — never merge a bulk-scroll filter that hits an unindexed field. The overhaul plan [Wave 1e](../refactoring/2026-07-04-code-overhaul-plan.md) makes this a lint rule.

### Coverage gap: `fetched_at` is only on 178 K of 6.2 M points

`fetched_at` is indexed but the payload is only present on original-crawler papers. **P2 promotions and P3 injections do not write `fetched_at`.** That means the `--recent-days` filter (added to `enrich-6-abstracts`, `enrich-4-refs-by-doi-via-s2`, `enrich-2-refs-by-doi-via-crossref` on 2026-07-06) narrows the scan to at most those 178 K points. This is the desired incremental behaviour — you only want to enrich what you just crawled — but if you ever need the enrichers to cover snapshot-injected papers you have to backfill `fetched_at` first (or gate on `snapshot_filled_at` instead, which is now indexed). Tracked as part of the [tier retrofit](../plans/TODO.md) plan.

---

## References

- Qdrant [collection config docs](https://qdrant.tech/documentation/concepts/collections/#update-collection-parameters)
- Qdrant [payload indexing docs](https://qdrant.tech/documentation/concepts/indexing/#payload-index)
- Related runbook: [`vllm-labeling.md`](vllm-labeling.md) (labeling is the biggest CPU consumer that motivated the CPU tuning above)
- Bulk vs incremental policy: [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md)
- 2026-07-06 root-cause notes in Wave 1e of [`../refactoring/2026-07-04-code-overhaul-plan.md`](../refactoring/2026-07-04-code-overhaul-plan.md)
- 2026-07-04 incident context in the v0.13.3 changelog in [`README.md`](../../README.md)
