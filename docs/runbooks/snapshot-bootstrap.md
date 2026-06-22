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

## Day 3 — P2 (covered in the separate Plan 3 runbook section)

(See `docs/runbooks/snapshot-bootstrap.md` after Plan 3 lands.)

## Day 6 — P3 (covered in the separate Plan 4 runbook section)

(See `docs/runbooks/snapshot-bootstrap.md` after Plan 4 lands.)

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

## Resume / restart

All phases are file-checkpointed. To re-run a phase from scratch:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p1 --confirm
```

(See Plan 4 for the `snapshot-status` / `snapshot-reset` commands.)
