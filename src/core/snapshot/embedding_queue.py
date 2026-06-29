"""Disk-persisted FIFO of points needing embedding, written by P2/P3.

Format: append-only JSONL at `embedding_queue.jsonl` under the checkpoint root.
A line is one of:
  {"point_id": <str>, "source": <str>}
  {"point_id": <str>, "cancelled": true}

Consumption pattern (caller acknowledges after successful processing):
  items = embedding_queue.peek_all()
  for batch in chunks(items, N):
      process(batch)                 # may raise
      embedding_queue.remove(batch)  # ack — items removed atomically

This explicit-ack design prevents data loss when the consumer crashes mid-
process. Historical incident 2026-06-29: the legacy `drain()` cleared the
file before the caller had embedded the points; a Qdrant 400 raised on the
very next line, and ~663K queued entries were lost. See
docs/incidents/2026-06-30-embed-queue-data-loss.md.
"""
import json
import os
from collections.abc import Iterator
from pathlib import Path


def _default_root() -> Path:
    return Path(os.environ.get("DAGSTER_HOME", str(Path.home() / "dagster_home"))) / "snapshot_checkpoints"


def _queue_file(root: Path | None) -> Path:
    r = root or _default_root()
    r.mkdir(parents=True, exist_ok=True)
    return r / "embedding_queue.jsonl"


def append(point_id: str, source: str, *, root: Path | None = None) -> None:
    f = _queue_file(root)
    with f.open("a") as fh:
        fh.write(json.dumps({"point_id": point_id, "source": source}) + "\n")


def cancel(point_id: str, *, root: Path | None = None) -> None:
    f = _queue_file(root)
    with f.open("a") as fh:
        fh.write(json.dumps({"point_id": point_id, "cancelled": True}) + "\n")


def _resolve(lines: list[str]) -> list[tuple[str, str]]:
    active: dict[str, str] = {}
    order: list[str] = []
    cancelled: set[str] = set()
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        pid = rec.get("point_id")
        if not pid:
            continue
        if rec.get("cancelled"):
            cancelled.add(pid)
            active.pop(pid, None)
            continue
        if pid in cancelled:
            continue
        if pid not in active:
            active[pid] = rec.get("source", "")
            order.append(pid)
    return [(pid, active[pid]) for pid in order if pid in active]


def depth(*, root: Path | None = None) -> int:
    f = _queue_file(root)
    if not f.exists():
        return 0
    return len(_resolve(f.read_text().splitlines()))


def peek_all(*, root: Path | None = None) -> list[tuple[str, str]]:
    """Return all unprocessed (point_id, source) entries WITHOUT clearing.

    Safe to call repeatedly. Use with `remove()` to acknowledge processed
    items — this two-step protocol survives consumer crashes."""
    f = _queue_file(root)
    if not f.exists():
        return []
    return _resolve(f.read_text().splitlines())


def remove(items: list[tuple[str, str]], *, root: Path | None = None) -> None:
    """Atomically remove processed (point_id, source) entries from the queue.

    Idempotent — calling with an item already gone is a no-op. Cancellation
    semantics preserved: appends a `cancelled=true` record per acknowledged
    point so the resolver drops them from future peek_all() results.
    """
    if not items:
        return
    f = _queue_file(root)
    with f.open("a") as fh:
        for pid, _src in items:
            fh.write(json.dumps({"point_id": pid, "cancelled": True}) + "\n")


def drain(*, root: Path | None = None) -> Iterator[tuple[str, str]]:
    """DEPRECATED — clears the queue file before the caller has processed
    the items, which loses data on consumer crash. Use peek_all() + remove()
    instead.

    Kept for backward compatibility with any external caller. Will be removed
    once internal callsites migrate. See the 2026-06-30 incident report.
    """
    import warnings
    warnings.warn(
        "embedding_queue.drain() loses data if the consumer crashes mid-process. "
        "Use peek_all() + remove() instead.",
        DeprecationWarning, stacklevel=2,
    )
    f = _queue_file(root)
    if not f.exists():
        return iter(())
    resolved = _resolve(f.read_text().splitlines())
    f.write_text("")  # clear after read — UNSAFE
    return iter(resolved)
