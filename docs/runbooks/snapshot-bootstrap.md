# Snapshot Utilization Bootstrap Runbook

Multi-day staged execution of the four snapshot passes against the local
OpenAlex `works` snapshot. Spec: `docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md`.

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

## Day 3 — P2 dry-run and full run

### Dry-run first

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
    --dry-run --limit-files 20
```

Inspect the printed summary:

```
p2 Summary: scanned=N matched=M ... stubs_seen=S promoted=P enriched=E merged=Me ...
```

Sanity:
- `promoted / matched` should be majority for high-quality stubs.
- `merged` reflects existing-real-paper collisions (good, not an error).
- `enriched` reflects partial metadata gains (also good).

### Full run

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot
```

Expected duration: ≈6–8 hours.

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
