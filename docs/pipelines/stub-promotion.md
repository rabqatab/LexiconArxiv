# Stub Promotion (P2)

P2 of the snapshot utilization system. For every stub in the corpus, match it
against the OpenAlex snapshot; promote, enrich, or merge.

## Decision rules

`src/core/snapshot/promotion.py:evaluate(stub, work_fields)`:

| Condition | Decision |
|---|---|
| `title` AND (`abstract` OR (`year` AND ≥1 author)) after the merge | `PROMOTE` |
| Some field is gained that the stub did not have | `ENRICH_KEEP_STUB` |
| Nothing gained | `SKIP` |

## Promotion transaction

Each promotion is a single-stub call to `storage.batch_promote_stubs`. Steps:

1. **Dedup guard** (`storage.find_real_by_identifier`): if any real paper
   already exists with this `doi` / `openalex_id` / `arxiv_id`, merge instead
   via `storage.merge_stub_into_real` (which unions `cited_by` into the real
   paper, dedups, and deletes the stub). Return `MERGED_INTO_EXISTING`.
2. **Payload swap** (`storage.set_payload`): write all extracted fields plus
   `is_stub=False`, `cited_by` preserved, `cited_by_count=len(cited_by)`,
   `cited_by_count_internal` preserved, `alternate_identifiers` preserved,
   `promoted_from_stub=True`, `promoted_at`, `snapshot_filled_at`.
3. **Verify** (read-back inside `batch_promote_stubs`): assert
   `is_stub is False` and `set(after.cited_by) >= set(stub.cited_by)`. If
   either fails, status `verify_failed` is returned and the caller raises
   `PromotionError`.
4. **Embedding queue**: if `work_fields["abstract"]` is present,
   `embedding_queue.append(point_id, source="promotion")`. The drain happens
   later via `embed-papers --consume-snapshot-queue`.

## Rollback

The transaction is idempotent (`set_payload` with the same key overwrites with
the same value), so the rollback strategy on partial failure is "next pass will
re-promote it":

- If verification fails, the point is quarantined to
  `${checkpoint_root}/p2/quarantine.jsonl` with the failing work. The operator
  inspects, decides whether to retry or hand-fix.
- If Qdrant goes down mid-batch, the failed batch is dumped to
  `${checkpoint_root}/p2/failed_batches/<ts>.jsonl`. Replay with
  `snapshot-replay-failed --phase p2`.

## Dedup safety

When `find_real_by_identifier` returns a real paper hit, `merge_stub_into_real`:

- Unions the stub's `cited_by` into the real paper's `cited_by`, sorted.
- Updates `cited_by_count`.
- Unions `alternate_identifiers`.
- Deletes the stub point.

This handles the race "incremental collection adds the real paper after the
stub was created" (TODO.md #16, now implemented).

## Corpus-level invariant

After a P2 run, the following must be 0:

```python
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
n = st.client.count(
    st.collection_name,
    count_filter=m.Filter(
        must=[m.FieldCondition(key="promoted_from_stub", match=m.MatchValue(value=True))],
        must_not=[m.IsEmptyCondition(is_empty=m.PayloadField(key="cited_by"))],
    ),
    exact=True,
).count
# Promoted with empty cited_by — but only count those that should have had citers:
# this needs the original cited_by-count from the pre-run snapshot to be meaningful.
```

A more useful check: spot-check 10 random `promoted_from_stub=True` points in the
search UI and verify each has a sensible `cited_by` list.
