"""Per-phase file-level checkpoint, failed-batch, and quarantine writes."""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _default_root() -> Path:
    return Path(os.environ.get("DAGSTER_HOME", str(Path.home() / "dagster_home"))) / "snapshot_checkpoints"


def _phase_dir(phase: str, root: Path | None) -> Path:
    p = (root or _default_root()) / phase
    p.mkdir(parents=True, exist_ok=True)
    return p


def load(phase: str, *, root: Path | None = None) -> set[str]:
    f = _phase_dir(phase, root) / "done_files.txt"
    if not f.exists():
        return set()
    return {ln.strip() for ln in f.read_text().splitlines() if ln.strip()}


def mark_done(phase: str, filepath: str, *, root: Path | None = None) -> None:
    """Append filepath to the done-files log.

    Idempotent at the consumer side (`load()` returns a set so duplicates are
    harmless). Skipping the read-before-write here keeps mark_done O(1) instead
    of O(N) over the file list — meaningful on the ~380-file OpenAlex snapshot.
    """
    f = _phase_dir(phase, root) / "done_files.txt"
    with f.open("a") as fh:
        fh.write(filepath + "\n")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_failed_batch(phase: str, batch: list, error: str, *, root: Path | None = None) -> Path:
    d = _phase_dir(phase, root) / "failed_batches"
    d.mkdir(exist_ok=True)
    f = d / f"{_ts()}.jsonl"
    with f.open("w") as fh:
        for item in batch:
            fh.write(json.dumps({"item": item, "error": error}) + "\n")
    return f


def quarantine(phase: str, work: dict, reason: str, *, root: Path | None = None) -> Path:
    f = _phase_dir(phase, root) / "quarantine.jsonl"
    with f.open("a") as fh:
        fh.write(json.dumps({"work": work, "reason": reason}) + "\n")
    return f


def reset(phase: str, *, root: Path | None = None) -> None:
    """Delete the phase's checkpoint dir but preserve quarantine.jsonl audit trail.

    `snapshot-reset` is an operator-facing destructive op (resume state, failed
    batches, etc. are dropped). The quarantine log is different — it's the audit
    trail of items that needed human inspection, and losing it on reset would
    silently destroy work tracking. Preserved as a sibling file.
    """
    p = (root or _default_root()) / phase
    if not p.exists():
        return
    quarantine_path = p / "quarantine.jsonl"
    quarantine_content = quarantine_path.read_bytes() if quarantine_path.exists() else None
    shutil.rmtree(p)
    if quarantine_content is not None:
        p.mkdir(parents=True, exist_ok=True)
        quarantine_path.write_bytes(quarantine_content)


def live_high_water_mark(phase: str, *, root: Path | None = None) -> str | None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    if not f.exists():
        return None
    s = f.read_text().strip()
    return s or None


def set_live_high_water_mark(phase: str, iso: str, *, root: Path | None = None) -> None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    f.write_text(iso)
