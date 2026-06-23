# Snapshot Utilization — Rollback Runbook

When a phase produced wrong results and you need to undo it.

## Scenario 1 — wrong P2 promotions

Symptom: promoted points lack expected cited_by, or wrong stubs were promoted.

```bash
# Reset the phase checkpoint
uv run python -m src.cli.core_collect snapshot-reset --phase p2 --confirm

# Identify promoted points from the affected window
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True))])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=['promoted_at','cited_by','title'])
for p in pts:
    print(str(p.id), p.payload.get('promoted_at'), p.payload.get('title'))
" > /tmp/promoted_audit.tsv
```

Manual review of `/tmp/promoted_audit.tsv`. To re-stub a wrong promotion
(restore `is_stub=True`, clear `promoted_from_stub`):

```python
storage.client.set_payload(
    collection_name=storage.collection_name,
    payload={"is_stub": True, "promoted_from_stub": False},
    points=[bad_point_id],
)
```

(Note: this is destructive at the payload level. Take a Qdrant snapshot first.)

## Scenario 2 — P3 injection runaway

Symptom: thousands of low-quality injections in the last run.

```bash
# Identify the bad batch by date
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[
    m.FieldCondition(key='injected_from_snapshot', match=m.MatchValue(value=True)),
    m.FieldCondition(key='injected_at', range=m.Range(gte='2026-06-21T00:00:00Z')),
])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=False)
print('to_delete:', len(pts))
ids = [str(p.id) for p in pts]
print(ids[:5])
" 
```

Then delete:

```python
storage.client.delete(
    collection_name=storage.collection_name,
    points_selector=models.PointIdsList(points=ids),
)
```

Re-run P3 with stricter thresholds:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect discover-corpus-gaps \
    --concept-min-recent 100 --concept-min-old 400 --max-injections 3000
```

## Scenario 3 — Qdrant data corruption

All snapshot phases are idempotent (`fill-only-missing` + provenance + dedup).
After restoring the Qdrant snapshot:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p1 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p2 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p4 --confirm
# Now rerun in order
uv run python -m src.cli.core_collect enrich-corpus-fields
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot
uv run python -m src.cli.core_collect discover-corpus-gaps
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot
```

## Scenario 4 — embedding queue lost

If the on-disk `embedding_queue.jsonl` was deleted/corrupted, reconstruct from
the corpus state:

```bash
uv run python -c "
from src.core.storage import QdrantStorage
from src.core.snapshot import embedding_queue
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(
    should=[
        m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True)),
        m.FieldCondition(key='injected_from_snapshot', match=m.MatchValue(value=True)),
    ],
    must_not=[
        m.HasVectorCondition(has_vector='structured-abstract'),
        m.IsEmptyCondition(is_empty=m.PayloadField(key='abstract')),
    ],
)
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=False)
for p in pts:
    embedding_queue.append(str(p.id), source='reconstructed')
print('requeued:', len(pts))
"
```
