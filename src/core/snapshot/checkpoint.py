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
    done = load(phase, root=root)
    if filepath in done:
        return
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
    p = (root or _default_root()) / phase
    if p.exists():
        shutil.rmtree(p)


def live_high_water_mark(phase: str, *, root: Path | None = None) -> str | None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    if not f.exists():
        return None
    s = f.read_text().strip()
    return s or None


def set_live_high_water_mark(phase: str, iso: str, *, root: Path | None = None) -> None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    f.write_text(iso)
