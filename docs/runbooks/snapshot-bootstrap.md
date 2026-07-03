# Snapshot Utilization Bootstrap Runbook

Multi-day staged execution of the four snapshot passes against the local
OpenAlex `works` snapshot. Spec: `docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md`.

> ⚠️ **Bootstrap alone is NOT enough.** P1→P4 populate ingestion-side payload
> only. Every downstream stage the incremental pipeline runs — labeling,
> keywords, references, embed, similarity, graph analysis, topic clusters —
> is still missing on the new papers. After P4 completes, follow
> [`post-bootstrap-catchup.md`](post-bootstrap-catchup.md) or the corpus
> silently degrades on 90% of the newly-added ~2-4M papers. Full audit of
> what's missing: [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md).

## Day 0 — pre-checks

```bash
# 1. SSD has room
df -h /mnt/nfs/ssd2

# 2. Snapshot present
du -sh /mnt/nfs/ssd2/openalex_snapshot/data/works
ls /mnt/nfs/ssd2/openalex_snapshot/data/works | wc -l   # should be ~380 dirs

# 3. Qdrant backed up (manual snapshot via the Qdrant UI or REST)

# 4. Embedding model ready (used later by drain step)
ollama list | grep qwen3-embedding

# 5. Baseline backlog
uv run python -m src.cli.core_collect embed-papers --dry-run
```

## Day 1 — P1 dry-run on a small slice

```bash
uv run python -m src.cli.core_collect enrich-corpus-fields \
    --dry-run --limit-files 50
```

Review the printed summary line:

```
p1 Summary: scanned=N matched=M applied=0 ... files_done=50 fields_filled_by_name={...}
```

If `matched / scanned` looks sensible and the field counter is non-empty,
proceed.

## Day 2 — P1 full run

```bash
uv run python -m src.cli.core_collect enrich-corpus-fields
```

Expected duration: ≈6 hours on the 594 GB snapshot.

After completion, verify DQ checks still pass:

```bash
uv run python -c "
from src.core.pipeline import dq
for name in ['abstract_coverage','embedding_coverage_complete','doi_papers_have_refs']:
    r = getattr(dq, name)()
    print(name, '=', 'PASS' if r['passed'] else 'FAIL', r['metadata'])
"
```

## Day 3 — P2 quality threshold + dry-run sweep + full run

### Pick the quality threshold (sweep dry-runs)

P2's `--min-cites-per-year` gate controls how aggressively stubs get promoted to
real papers. **Default 0 means promote everything that matches** — on a
~3.45M-stub corpus this is 1.5–2.5M promotions and ~2 weeks of embedding work.
For an operational bootstrap, pick a threshold that bounds scope.

Sweep 3–4 thresholds on the same 5 recent files (each takes ~4 min):

```bash
SNAP=/mnt/nfs/ssd2/openalex_snapshot/data/works
DAGSTER_HOME=${DAGSTER_HOME:-$HOME/dagster_home}
for RATE in 0 1 5 10; do
    rm -rf "$DAGSTER_HOME/snapshot_checkpoints/p2"
    mkdir -p "$DAGSTER_HOME/snapshot_checkpoints/p2"
    ls $SNAP/updated_date=*/*.gz | sort | head -n -5 | xargs -I{} realpath {} \
        > "$DAGSTER_HOME/snapshot_checkpoints/p2/done_files.txt"
    echo "--- min-cites-per-year=$RATE ---"
    uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
        --snapshot-dir $SNAP --dry-run --resume \
        --min-cites-per-year $RATE --now-year 2026 2>&1 | grep "p2 Summary" | tail -1
done
rm -rf "$DAGSTER_HOME/snapshot_checkpoints/p2"
```

Note: recent files skew toward well-cited papers, so `promoted/matched` here
overstates what the full run will produce on older files (which carry more
long-tail). Use the sweep to compare *relative* impact across thresholds.

### Recommended starting threshold

| Goal | Use |
|---|---|
| Sustainable scope (recommended) | `--min-cites-per-year 5` (~500K-1M promotions, 4-7 days embed) |
| Conservative | `--min-cites-per-year 10` (~300K-650K promotions, 2-4 days embed) |
| Maximal coverage | `--min-cites-per-year 0` (~1.5-2.5M promotions, 11-18 days embed) |

See [`docs/pipelines/stub-promotion.md` — Quality gate](../pipelines/stub-promotion.md#quality-gate---min-cites-per-year)
for the full decision-rule table and worked examples.

### Sanity checks on the dry-run output

```
p2 Summary: scanned=N matched=M ... stubs_seen=S promoted=P enriched=E merged=Me ...
```

- `promoted / matched` decreases as `--min-cites-per-year` rises (papers below
  the rate fall to `enriched`).
- `merged` reflects existing-real-paper collisions (good, not an error).
- `enriched` reflects gated promotions + partial metadata gains (also good — the
  citation-graph data is preserved on the stub regardless).

### Full run

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
    --min-cites-per-year 5 --now-year 2026
```

Expected duration: ≈24–30 hours (full snapshot scan + Qdrant writes).
Adjust `--min-cites-per-year` per your threshold sweep result above.

> **Performance note**: P2 startup auto-creates payload indices on
> `doi`/`openalex_id`/`arxiv_id` via `ensure_identifier_indices()` — without
> these, each promotion does ~3 full-collection scans (~4.2s each on a 3.6M-
> point corpus) and throughput drops to ~1.6K writes/hr (extends ETA to
> 11+ days). The first P2 run on an existing collection will spend ~60 seconds
> upfront building the indices, then proceed at full ~75K-117K writes/hr. See
> [docs/pipelines/stub-promotion.md — Performance](../pipelines/stub-promotion.md#performance--payload-indices-are-required).

### Post-run verification

1. **Invariant query** — every promoted point with a non-empty stub `cited_by`
   list should still carry that list:

```bash
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True))])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=20,
                          with_payload=['cited_by','cited_by_count'])
for p in pts:
    print(str(p.id)[:8], 'cited_by=', len(p.payload.get('cited_by') or []),
          'count=', p.payload.get('cited_by_count'))
"
```

Every line should show a non-zero `cited_by`. If any is 0, inspect the
quarantine file:

```bash
ls -la ~/dagster_home/snapshot_checkpoints/p2/quarantine.jsonl
```

2. **DQ checks still pass.**

```bash
uv run python -c "
from src.core.pipeline import dq
for n in ['abstract_coverage','embedding_coverage_complete','doi_papers_have_refs','real_papers_have_titles']:
    r = getattr(dq, n)()
    print(n, '=', 'PASS' if r['passed'] else 'FAIL', r['metadata'])
"
```

## Day 4–5 — drain the embedding queue

```bash
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
```

(`--consume-snapshot-queue` flag is added in Plan 4.) Wait until the queue is
empty before moving on:

```bash
uv run python -m src.cli.core_collect snapshot-status
```

(Also added in Plan 4.)

## Day 6 — P3 dry-run + staged real run

### Dry-run on a slice

```bash
uv run python -m src.cli.core_collect discover-corpus-gaps \
    --dry-run --limit-files 30
```

Inspect:
- `anchor_inject / scanned` — should be a small fraction of a percent
- `concept_inject / scanned` — likewise; tune `--concept-min-recent` / `--concept-min-old`
  if too high
- `year_distribution` — heavy 2022–2025 expected, very few pre-2018 (the floor)
- `top_concepts` — should match your AI focus

### Capped real run

```bash
uv run python -m src.cli.core_collect discover-corpus-gaps --max-injections 5000
```

Review the summary line and verify a sample of injected points in the search UI.

### Full run (after the capped run looks healthy)

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect discover-corpus-gaps
```

Expected duration: ≈4–8 hours.

## Day 7-9 — drain P3 embedding queue

Same procedure as Day 4-5 after P2:

```bash
uv run python -m src.cli.core_collect snapshot-status   # check queue depth
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
```

## Day 10 — P4 full run

P4 must run **after** P2 + P3 are complete AND `embedding_queue` is drained,
so newly promoted/injected points also get their external citers attached.

```bash
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot \
    --max-citers-per-paper 300
```

Expected duration: ≈2–3 hours.

Verify:

```bash
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
n = st.client.count(
    st.collection_name,
    count_filter=m.Filter(
        must_not=[m.IsEmptyCondition(is_empty=m.PayloadField(key='external_cited_by'))]
    ),
    exact=True,
).count
print('papers with external_cited_by:', n)
"
```

## Day 11+ — re-run analytics

```bash
uv run python -m src.cli.core_collect compute-similarity
uv run python -m src.cli.core_collect analyze-graph
uv run python -m src.cli.core_collect compute-topics
```

## Day 12+ — enable daily live mode

After two weeks of clean bootstrap operations and a successful drain of the
embedding queue, enable the daily live worker so corpus stays current.

### Smoke-test the live worker once manually

```bash
uv run python -m src.cli.core_collect snapshot-live-delta --days-back 1 --dry-run
```

Verify the printed summary line shows `fetched=N` (non-zero) and no
`worker_errors`. Inspect a sample by widening the date range to confirm the
classifier picks up real AI-domain works:

```bash
uv run python -m src.cli.core_collect snapshot-live-delta --since 2026-06-22 --dry-run --max-injections 20
```

### Enable the schedule

In the Dagster UI, locate `daily_snapshot_live_schedule` and flip it from
STOPPED → RUNNING. Or, in code, change `default_status=DefaultScheduleStatus.RUNNING`
in `src/orchestration/schedules.py` and redeploy.

### Monitor

The first week, check daily in the Dagster UI's asset page:
- `snapshot_live_delta` materialization metadata shows
  `fetched`/`p1.matched`/`p2.promoted`/`p3.anchor_inject`/`p3.concept_inject`/`p4.applied`.
- Embedding queue depth (visible in `snapshot-status` CLI) should drain on the
  next `core_pipeline_job` run.

### Rollback

Flip the schedule back to STOPPED and the corpus stops getting daily updates
without any other side effect. The HWM file remains, so re-enabling resumes
from the next day after the last successful pass.

## Resume / restart

All phases are file-checkpointed. To re-run a phase from scratch:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p1 --confirm
```

(See Plan 4 for the `snapshot-status` / `snapshot-reset` commands.)
