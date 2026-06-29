# Embed queue data loss — 663K queued entries destroyed in 3 seconds

**Date:** 2026-06-30
**Severity:** High — silent data loss; ~3 days of bootstrap rework needed
**Status:** Resolved (recovery embed running, code fixed in commit `<this commit>`)
**Resolution time:** ~30 minutes from detection to safe recovery launch

## TL;DR

Submitted `embed-papers --consume-snapshot-queue` to consume the 663K embed queue P2 had built up. Job failed in **3 seconds** on a malformed Qdrant `Filter(must=[HasIdCondition(has_id=pids)])` (400 Bad Request — `Expected some form of condition`). But `embedding_queue.drain()` had already cleared the on-disk JSONL file in the same call **before** the consumer processed the items. The queue is empty, the entries are unreachable. Recovery launched via default-scroll mode (uses `HasVectorCondition` to skip already-embedded papers — finds the ~1M un-embedded papers safely, ~7-day ETA vs ~4.5d for the targeted-queue path).

## Timeline

| Time (UTC+9) | Event |
|---|---|
| 2026-06-30 00:14:43 | `sparkq submit` of job `8995` with `--consume-snapshot-queue` flag |
| 2026-06-30 00:14:44 | Job started, opened Qdrant + Ollama connections OK |
| 2026-06-30 00:14:45 | `embedding_queue.drain()` called — **663,606 lines read from disk, file truncated to 0 bytes** |
| 2026-06-30 00:14:47 | `client.scroll(scroll_filter=Filter(must=[HasIdCondition(has_id=pids)]))` raised `UnexpectedResponse: 400` — `embedding_queue.jsonl` is now empty |
| 2026-06-30 00:14:47 | Process exited; sparkq recorded `failed_final` |
| 2026-06-30 00:55:00 | Operator checked status, saw 3-sec runtime + empty queue file |
| 2026-06-30 00:56:00 | Truth source measured: 1,150,106 non-stubs, 148,297 embedded, ~1M needing embedding |
| 2026-06-30 00:57:00 | Recovery job `e3be` submitted with default scroll (no `--consume-snapshot-queue`) — uses `HasVectorCondition` to skip already-embedded |
| 2026-06-30 01:05:00 | Code fix shipped: explicit-ack queue pattern + `client.retrieve()` for batched id lookups + per-chunk acknowledgment |

## Root cause — TWO bugs compounded

### Bug A — `Filter(must=[HasIdCondition(has_id=pids)])` rejected by Qdrant

```python
# src/cli/commands/embedding.py:137 (pre-fix)
pts, _ = storage.client.scroll(
    collection_name=storage.collection_name,
    scroll_filter=m.Filter(must=[m.HasIdCondition(has_id=pids)]),
    ...
)
```

Two problems with this call:

1. The Qdrant server returned `Expected some form of condition` — the `HasIdCondition` nested inside `must` was not accepted by the deployed Qdrant version's parser (or the JSON body simply didn't deserialize because of the next problem).
2. `pids` was a 663,606-item list. The serialized request body crossed the server's body-size limit (~16MB default). A truncated body would parse as an empty/malformed filter.

Either way, the call was guaranteed to fail on any non-tiny queue. The right primitive for "fetch these specific points by id" is `client.retrieve(ids=[...])`, not `client.scroll(scroll_filter=Filter(...))`.

### Bug B — `embedding_queue.drain()` cleared the file BEFORE the consumer processed items

```python
# src/core/snapshot/embedding_queue.py:73-79 (pre-fix)
def drain(*, root: Path | None = None) -> Iterator[tuple[str, str]]:
    f = _queue_file(root)
    if not f.exists():
        return iter(())
    resolved = _resolve(f.read_text().splitlines())
    f.write_text("")  # clear after read   ← UNSAFE
    return iter(resolved)
```

The file was truncated inside `drain()` itself, before the caller had embedded anything. When the next line crashed, the in-memory `resolved` list went out of scope and 663K entries were gone with no on-disk trace.

This is a classic message-queue antipattern: **read-and-delete in one step**. Every durable queue (Kafka, RabbitMQ, SQS) decouples "give me messages" from "I successfully processed these — remove them" precisely for this reason.

## Detection

Per `systematic-debugging` Phase 1 (don't fix, gather evidence):

1. **Reproduce** — automatic; the failure is at the very first scroll call, deterministic.
2. **Read errors carefully** — sparkq's `failed_final` status + 3-sec runtime + the Qdrant 400 trace immediately localized the failure to the `--consume-snapshot-queue` block.
3. **Check side effects** — measured `embedding_queue.depth()` → 0 (was 663,606 minutes earlier). The 0-byte file mtime matched the job start time. Conclusion: drain() destroyed the queue.
4. **Truth source** — counted non-stubs (1,150,106) vs non-stubs-with-embeddings (148,297). ~1M points need embedding regardless of whether the queue exists.
5. **Recovery options weighed** —
   a. Reconstruct queue from logs? P2's log shows promotions but not the queue writes; would miss entries.
   b. Re-run P2 to re-queue? P2 is idempotent — re-running would hit "nothing gained" path and NOT re-queue. Useless.
   c. Default scroll mode? `get_papers_for_embedding(skip_embedded=True)` uses `HasVectorCondition` server-side — finds exactly the ~1M un-embedded papers, slower than targeted-queue but doesn't depend on the destroyed queue. **Selected.**

## Resolution

### Immediate (recovery in flight)

`sparkq submit` of job `e3be` with `embed-papers --resume` (no `--consume-snapshot-queue`). The default scroll loop in `embed-papers` uses `storage.get_papers_for_embedding(skip_embedded=True)` which applies `HasVectorCondition` at Qdrant — only papers without an `abstract-qwen3-8b` vector are yielded. Slower than the targeted queue path (~7 days vs ~4.5 days at the same throughput) but doesn't require the destroyed queue.

### Permanent (this commit)

**Queue ack protocol** (`embedding_queue.py`):

```python
# Replace read-and-delete drain() with explicit-ack pattern:
items = embedding_queue.peek_all()         # read, file untouched
for batch in chunks(items, N):
    process(batch)                          # may raise
    embedding_queue.remove(batch)           # ack: append cancelled=true records
```

- `peek_all()` is idempotent — calling it again returns the same items.
- `remove(items)` is idempotent — appends `cancelled=true` for each (resolver drops them).
- `drain()` retained but emits `DeprecationWarning` for any external caller. Will be removed once no internal use remains.

**Qdrant call** (`embed-papers --consume-snapshot-queue`):

```python
# Replace the broken Filter(must=[HasIdCondition(has_id=huge_list)]) scroll
# with chunked client.retrieve(ids=...) — the right primitive for id lookups.
CHUNK = 500
for i in range(0, len(queued), CHUNK):
    chunk = queued[i:i + CHUNK]
    records = storage.client.retrieve(
        collection_name=..., ids=[pid for pid, _ in chunk], ...
    )
    # ...embed...
    embedding_queue.remove(chunk)  # ack per chunk
```

Chunking serves both the request-size limit (500 ids × ~80 bytes = 40KB, well under any sane limit) and the durability story (per-chunk ack means a crash mid-loop loses at most one chunk's worth of work, not the entire queue).

### Regression tests

5 new tests in `tests/core/snapshot/test_embedding_queue.py` lock the explicit-ack semantics, especially `test_consumer_crash_does_not_lose_items` which directly reproduces this incident's scenario and asserts the items survive across consumer "crashes". A 6th test ensures the legacy `drain()` still emits its deprecation warning. **100/100 unit tests pass.**

## Test gap analysis

Two latent gaps allowed this through review and CI:

1. **The Plan 5 task-4 review for `--consume-snapshot-queue`** only checked that the option appeared in `--help` output. It did not exercise the code path against a real Qdrant collection with a non-trivial queue size. The Qdrant Filter syntax bug would have surfaced in any L3 test that wired `peek_all()` to `retrieve()` and embedded even 100 entries.

2. **`drain()`'s `f.write_text("")` was reviewed as a feature, not a hazard.** The Plan 1 reviewer noted "rewrites the file empty after a successful drain" as if it were safe. A simple thought experiment ("what if the caller crashes before processing the iterator?") would have caught it. The lesson generalizes: **any function that mutates persistent state in the name of a future caller's action is suspect**.

## Action items

| # | Item | Status |
|---|---|---|
| 1 | Replace `drain()` with `peek_all()` + `remove()` explicit-ack pattern | ✅ This commit |
| 2 | Replace broken Qdrant Filter with chunked `client.retrieve(ids=...)` | ✅ This commit |
| 3 | Add `test_consumer_crash_does_not_lose_items` and 4 supporting tests | ✅ This commit |
| 4 | `drain()` emits `DeprecationWarning` (kept for transitional compat) | ✅ This commit |
| 5 | Recover by re-embedding via default scroll (`embed-papers --resume`) | 🔄 Running (job `e3be`) |
| 6 | Update `docs/pipelines/snapshot-live-mode.md` to call out the queue ack contract for any future live-mode worker code | ⏳ Deferred (low priority — `live_worker.run_live_delta` only peeks queue depth, doesn't drain) |
| 7 | Audit any other Qdrant `client.scroll(scroll_filter=Filter(must=[HasIdCondition(...)]))` callsites | ✅ Checked: 4 other sites in `stubs.py`/`writer.py` all use `has_id=[single_pid]` (1-item lists), safe |
| 8 | Add an L3 integration test that drives `embed-papers --consume-snapshot-queue` end-to-end against a small Qdrant fixture | ⏳ Deferred to post-bootstrap polish wave |

## Lessons learned

1. **Read-and-delete is a bug pattern.** Any function that mutates persistent state on behalf of an uncompleted future action is suspect. The fix is always the same: split into `get` (idempotent) + `ack` (idempotent), called separately by the consumer.

2. **`scroll_filter=Filter(must=[HasIdCondition(...)])` is the wrong primitive for "fetch these specific ids".** Use `client.retrieve(ids=[...])` — it's named what it does, batches under the hood, and doesn't require constructing 500KB JSON filter bodies. The qdrant-client API has both for a reason.

3. **Single 663K-item HTTP requests will fail somewhere — server body limit, JSON parser timeout, network MTU.** Chunk anything that scales with corpus size. Pick a chunk size from observed throughput, not "as big as possible".

4. **`--help` tests prove syntax, not behavior.** The Plan 5 Task 4 reviewer (and I, as controller) accepted a CLI test that just checked `--help` printed. The actual code path was never exercised. Every CLI command that crosses a system boundary (DB, network, queue) needs at least one integration test that runs end-to-end on real fixtures. Cost is real (slow CI), but as the 2026-06-29 indices incident and this one showed, the alternative is real production bootstrap rework measured in days.

5. **Recovery via the safe path is almost always cheaper than racing a buggy fast path.** ~7 days via default scroll vs ~4.5 days via fixed targeted scroll. The 2.5-day savings on the fast path is *worth nothing* if there's any non-trivial risk of a third bug in the now-twice-touched `--consume-snapshot-queue` code. Ship the recovery, fix the bugs in a separate effort, validate against a small queue before relying on the fast path again.

## References

- Predecessor incident (same bootstrap): [`2026-06-29-p2-missing-payload-indices.md`](2026-06-29-p2-missing-payload-indices.md)
- Code fix: this commit
- Audit reference: [`docs/refactoring/2026-06-24-ponytail-audit.md`](../refactoring/2026-06-24-ponytail-audit.md) — file an item there for the L3 integration test gap
- Queue protocol: `src/core/snapshot/embedding_queue.py` module docstring
- Consumer pattern: `src/cli/commands/embedding.py` `--consume-snapshot-queue` block
- Regression tests: `tests/core/snapshot/test_embedding_queue.py` (5 new tests)
