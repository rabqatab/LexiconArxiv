# Stub Promotion (P2)

P2 of the snapshot utilization system. For every stub in the corpus, match it
against the OpenAlex snapshot; promote, enrich, or merge.

## Decision rules

`src/core/snapshot/promotion.py:evaluate(stub, work_fields, *, min_cites_per_year=0.0, now_year=None)`:

| Condition | Decision |
|---|---|
| Nothing gained from the merge | `SKIP` |
| Base PROMOTE criteria met (`title` AND (`abstract` OR (`year` AND ≥1 author))) **AND** age-normalized citation rate ≥ `min_cites_per_year` | `PROMOTE` |
| Otherwise (base criteria fail OR rate below threshold) | `ENRICH_KEEP_STUB` |

### Quality gate: `--min-cites-per-year`

A flat `cited_by_count` threshold is unfair to recent papers — citation counts
accumulate over time, so a 2026 paper with 5 cites and a 2010 paper with 5 cites
are not the same signal. P2 uses an **age-normalized rate**:

```
rate = cited_by_count / max(1, now_year - publication_year)
PROMOTE only if rate >= min_cites_per_year
```

| `min_cites_per_year` | What it admits |
|---|---|
| `0` (default) | Everything (no gate) — bootstrap-conformant maximal coverage |
| `1` | Any paper still being cited at all (~3% trim on the recent slice) |
| `5` | "Five times a year, every year" — captures both recent influential work and durable classics |
| `10` | Strict — recent landmarks + foundational old papers only |

Worked examples (with `now_year=2026`):

| Paper | cites | year | rate | passes 5.0? |
|---|---|---|---|---|
| Recent landmark | 5 | 2025 | 5.0 | ✅ |
| Old classic | 80 | 2010 | 5.0 | ✅ |
| Old long-tail | 5 | 2010 | 0.31 | ❌ → `ENRICH_KEEP_STUB` |
| Current year buzz | 3 | 2026 | 3.0 (divided by `max(1, 0)=1`) | ❌ → `ENRICH_KEEP_STUB` |
| Missing year | 100 | — | n/a | ❌ → `ENRICH_KEEP_STUB` (gated conservatively) |

**Important**: gated papers don't get dropped — they fall to `ENRICH_KEEP_STUB`,
which still fills payload gaps (snapshot-derived title/year/authors/topics/etc.)
but leaves `is_stub=True`. So the citation-graph data is preserved either way;
only the search-index membership is gated.

### Recommended starting values

| Goal | Use |
|---|---|
| First bootstrap on a 175K-real / 3.45M-stub corpus | `--min-cites-per-year 5` (≈ 500K-1M promotions, 4-7 days embed) |
| Conservative — keep corpus tight to AI/CS canon | `--min-cites-per-year 10` (≈ 300K-650K promotions, 2-4 days embed) |
| Spec-conformant maximal coverage | `--min-cites-per-year 0` (≈ 1.5-2.5M promotions, 11-18 days embed) |

Re-run with a different threshold at any time — P2 is idempotent and resumable.

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

### Verify-failed recovery (operator action required)

Spec §6 originally prescribed a backup/restore semantic where a verify failure
would auto-revert `is_stub` back to `True`. The implementation does NOT do this —
`batch_promote_stubs` writes the new payload (including `is_stub=False`) before
the read-back verify. If verify fails, the point is in a **partially-promoted
state**: `is_stub=False` but `cited_by` may not equal the stub's original list.

Subsequent P2 passes will NOT re-pick it up (the iterator filters by
`is_stub=True`). Two operator paths:

1. **Trust the partial promotion** — the corpus has a new real paper whose
   `cited_by` may be incomplete. Acceptable if you can rebuild `cited_by` later
   (e.g. via `build_cited_by_incremental`).
2. **Hand-revert** — read the quarantined work from `${checkpoint_root}/p2/quarantine.jsonl`,
   inspect the affected `point_id`, and either:
   - `storage.set_payload(point_id, {"is_stub": True, "promoted_from_stub": False})`
     to re-stub it for the next pass, OR
   - apply the original stub's `cited_by` back to the now-real paper.

In practice verify_failed requires Qdrant to silently accept a write but return
different content on read-back. Quarantine.jsonl is the audit trail.

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
