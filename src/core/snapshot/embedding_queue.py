"""Disk-persisted FIFO of points needing embedding, written by P2/P3.

Format: append-only JSONL at `embedding_queue.jsonl` under the checkpoint root.
A line is one of:
  {"point_id": <str>, "source": <str>}
  {"point_id": <str>, "cancelled": true}

`drain` returns (point_id, source) tuples in insertion order, deduped, with
cancellations honored, and rewrites the file empty after a successful drain.
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


def drain(*, root: Path | None = None) -> Iterator[tuple[str, str]]:
    f = _queue_file(root)
    if not f.exists():
        return iter(())
    resolved = _resolve(f.read_text().splitlines())
    f.write_text("")  # clear after read
    return iter(resolved)
