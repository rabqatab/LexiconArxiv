# P2 missing payload indices — 140× production slowdown

**Date:** 2026-06-29
**Severity:** High — bootstrap operational schedule blown up (24-30h → 11+ days)
**Status:** Resolved, root cause + permanent fix shipped (commit `82ef621`)
**Resolution time:** ~30 minutes from detection to verified fix in production

## TL;DR

P2 (`resolve-stubs-from-snapshot`) was running at **1.6K writes/hr** instead of the expected ~25-30K/hr because Qdrant payload indices were missing on the three identifier fields (`doi`, `openalex_id`, `arxiv_id`) that `find_real_by_identifier` filters on. Each promotion was doing 3 full-collection scans (3.6M points) at 4.2 sec each. Added `ensure_identifier_indices()` (idempotent, auto-called at `ensure_collection()` + every P2 startup). Same scroll dropped from 4.2s to 17ms (250× faster); production throughput rose to **225K writes/hr** (140× faster end-to-end).

## Timeline

| Time (UTC+9) | Event |
|---|---|
| 2026-06-26 09:33 | P2 launched with `--min-cites-per-year 5` (initial est. ~24-30h) |
| 2026-06-26 11:33 | First status check: 11.3% in 2h, 7.5K writes/hr — looked normal |
| 2026-06-26 14:30 | Pace dropping: 5K writes/hr |
| 2026-06-29 09:55 | 3 days elapsed, only 21.8% done. Linear ETA had ballooned to 260h |
| 2026-06-29 10:05 | Operator escalated for investigation (`systematic-debugging` skill invoked) |
| 2026-06-29 10:10 | Phase 1.4 evidence: `payload_schema` query showed only `is_stub`/`venue`/`fetched_at` indexed; single filter scroll measured at 4.2 sec |
| 2026-06-29 10:12 | Manually created indices on `doi`/`openalex_id`/`arxiv_id` via Qdrant API (60s total build time) — same scroll now 17 ms |
| 2026-06-29 10:18 | P2 restarted with `--resume` (continued from file 463 / 2127) |
| 2026-06-29 10:25 | Code fix committed (`82ef621`) — `ensure_identifier_indices()` auto-called at collection + phase startup |
| 2026-06-29 13:14 | Status check: P2 at 41.6%, sustained **225K writes/hr**, ETA ~9h to completion |

## Root cause

### The query pattern

P2's `promote_one()` calls `storage.find_real_by_identifier(stub)` for every matched stub as a dedup guard before promoting. That function does up to three sequential Qdrant `scroll()` calls, one per identifier type, each with a `Filter(must=[FieldCondition(key=<id_field>, ...)], must_not=[FieldCondition(key="is_stub", ...)])`:

```python
# src/core/storage/stubs.py:851-871 (find_real_by_identifier)
for key in ("doi", "openalex_id", "arxiv_id"):
    v = fields.get(key)
    if not v:
        continue
    flt = models.Filter(
        must=[models.FieldCondition(key=key, match=models.MatchValue(value=v))],
        must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))],
    )
    pts, _ = self.client.scroll(collection_name=..., scroll_filter=flt, limit=1, ...)
    if pts:
        return str(pts[0].id)
return None
```

### What Qdrant did without indices

A `scroll()` call with a payload-field filter against an **unindexed** field forces Qdrant to materialize each point's payload and evaluate the filter inline — a full collection scan. On `lexicon_arxiv_v3` (3.6M points), one such scroll measured **4.2 seconds**.

Per promotion: ~3 scrolls × 4.2 s = **~12 seconds Qdrant time spent purely on dedup lookups**, before any actual write happened.

### Why throughput was 1.6K/hr (not zero)

Each promotion also did one `set_payload()` write + one `HasIdCondition` verify scroll (both fast, point-id based). At the same time, the loop wasn't perfectly serial — `qdrant-client` reused connections and Qdrant kept its segment caches warm. Observed: 1.6K writes/hr in the slow phase (after early small files were processed).

### Why the indices were missing

Only three indices existed at runtime:

```
is_stub:    bool   (3,453,513 pts) — created by ensure_stub_payload_index()
venue:      text   (270,028 pts)    — created by ensure_venue_text_index()
fetched_at: datetime (175,649 pts)  — auto-indexed by storage layer
```

`doi`, `openalex_id`, `arxiv_id` had **no `ensure_*_index()` method** when the stub system was designed. The Plan 2 spec described `find_real_by_identifier` as a dedup guard but didn't specify the index requirement. The integration tests passed because they exercised the storage extension methods directly (small fixture data) — not the phase orchestration on a real-sized corpus.

## Detection

Followed the `systematic-debugging` skill's Phase 1 (root cause investigation, no fixes first):

1. **Reproduce** — observable: pace dropping over 3 days from 7.5K → 5K → 1.6K writes/hr. ETA extrapolation gave 260h, far outside the spec estimate.
2. **Check recent changes** — none; P2 code hadn't changed in days.
3. **Multi-component evidence** — measured each layer:
   - `wc -l` on `done_files.txt`: 463/2127 in 72h = ~6.4 files/hr (file rate slowing as recent files are larger)
   - Log write count: 117K POST `/points/payload?wait=true` calls / 72h = ~1.6K writes/hr
   - **Single isolated scroll query against Qdrant: 4.2 seconds** ← the smoking gun
4. **Hypothesis** — payload indices missing on the query-hot identifier fields. Predicted: with indices, scroll should drop to <100ms.
5. **Test minimally** — manually issued `PUT /collections/.../index` for each field (no code change yet). Re-ran same scroll: 17ms. Hypothesis confirmed.

Each step took ~1-2 minutes; total investigation 30 min.

## Resolution

### Immediate (manual, while P2 was killed)

```bash
for FIELD in doi openalex_id arxiv_id; do
    curl -X PUT "http://localhost:6333/collections/lexicon_arxiv_v3/index?wait=true" \
        -H "Content-Type: application/json" \
        -d "{\"field_name\":\"$FIELD\",\"field_schema\":\"keyword\"}"
done
```

Index build took ~20 seconds per field (60s total). Restarted P2 with `--resume`.

### Permanent (committed in `82ef621`)

New method `QdrantStorage.ensure_identifier_indices()` (idempotent — Qdrant `create_payload_index` is a no-op when the index exists) called from:
- `ensure_collection()` — newly-created collections get the indices automatically.
- `phase2_stub_resolution.run()` startup — existing collections get the indices on their first P2 run.

```python
def ensure_identifier_indices(self) -> None:
    """Create keyword indices on doi/openalex_id/arxiv_id for fast lookups.
    Without these, every P2 promotion does ~3 filtered scrolls that
    full-scan the collection (~4 sec on 3.6M points = ~13 sec per
    promotion). With them, each scroll is <20ms — ~250x speedup."""
    for field in ("doi", "openalex_id", "arxiv_id"):
        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # Already exists
```

Regression test extended (`tests/core/snapshot/test_storage_compat.py`) — `ensure_identifier_indices` added to the phase-method assertion list, so future divergence between the perf-critical interface and the real storage class is caught in CI.

## Test gap analysis

The bug was latent through:
- 95/95 unit tests — `mock_storage` is a Python dict; scroll/filter/index semantics don't exist there
- 12/12 integration tests — exercise storage *extension methods* directly with tiny fixtures (a few hundred points); never the phase orchestration loop against a realistically-sized Qdrant collection

What would have caught it:
- **L3 perf test** — a test that runs `phase2_stub_resolution.run()` against a Qdrant instance with ≥100K points and asserts throughput ≥ N promotions/sec. (Too expensive for CI; would need a dedicated weekly perf job.)
- **Startup lint** — assert that every payload field appearing in a `Filter(must=[FieldCondition(key=X, ...)])` call across the phase modules has an index on the target collection. Fast (~1 second), catches the issue at boot before throughput dies. **Filed as audit item #21.**

## Action items

| # | Item | Status |
|---|---|---|
| 1 | `ensure_identifier_indices()` shipped (`82ef621`) | ✅ Done |
| 2 | Storage-compat regression test pins the method | ✅ Done |
| 3 | Pipeline doc gets a Performance section explaining the index requirement | ✅ Done (`stub-promotion.md`) |
| 4 | Bootstrap runbook flags the index dependency in the Day 3 P2 section | ✅ Done |
| 5 | Audit doc records the perf bug + generalizable improvement | ✅ Done (item #21) |
| 6 | Startup-check linter that warns on unindexed query-hot payload fields | ⏳ Deferred (audit item #21 — to do during post-bootstrap polish wave) |
| 7 | Audit P3 and P4 for similar latent perf bugs against the production collection | ⏳ Deferred (defer until bootstrap is done; ad-hoc dry-run timing checks are cheap to run any time) |

## Lessons learned

1. **Mock storage is not a substitute for index semantics.** Any storage feature that depends on the backend's query planner (indices, B-trees, vector search) needs at least one L3 test against the real backend at meaningful scale. The unit-test pass rate gave false confidence.

2. **Slowdowns compound non-linearly across file size + index miss.** Early symptoms looked like file-size variance (small old files fast, large recent files slow) and we almost dismissed the trend. The single isolated scroll measurement (4.2s) was decisive — one direct measurement at a component boundary beats hours of extrapolation.

3. **Storage performance is a payload-schema concern, not a phase concern.** The fix lives in `src/core/storage/base.py:ensure_identifier_indices()` and is auto-called at the right two places (collection creation + phase startup). Phases shouldn't have to remember to maintain indices.

4. **`--resume` is the real safety net.** Killing P2 mid-run was costless — the checkpoint had `done_files.txt` up to file 463; the resumed run picked up at file 464 and skipped no work. Every long-running phase MUST have file-level checkpointing that survives a kill-9.

5. **Diagnostic discipline pays back fast.** Following `systematic-debugging` Phase 1 (don't fix, gather evidence first) took ~30 minutes total. Without it, the temptation would have been to start tuning batch sizes or worker counts — fixes that wouldn't have touched the actual bottleneck.

## References

- Code fix: commit [`82ef621`](https://github.com/rabqatab/LexiconArxiv/commit/82ef621)
- Audit item: [`docs/refactoring/2026-06-24-ponytail-audit.md`](../refactoring/2026-06-24-ponytail-audit.md) item #21
- Pipeline reference: [`docs/pipelines/stub-promotion.md` — Performance](../pipelines/stub-promotion.md#performance--payload-indices-are-required)
- Runbook reference: [`docs/runbooks/snapshot-bootstrap.md`](../runbooks/snapshot-bootstrap.md) Day 3 P2 section
- Storage compat test: `tests/core/snapshot/test_storage_compat.py`
