"""P4: extend-cited-by-from-snapshot — corpus-internal external_cited_by."""
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import work_source
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p4"


def _citer_entry(work: dict) -> dict:
    return {
        "openalex_id": (work.get("id") or "").rsplit("/", 1)[-1],
        "year": work.get("publication_year"),
        "venue": ((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "cited_by_count": work.get("cited_by_count"),
    }


def _hits(work: dict, oa_to_pid: dict[str, str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ref in work.get("referenced_works") or []:
        wid = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None
        if not wid:
            continue
        if pid := oa_to_pid.get(wid):
            out.append((wid, pid))
    return out


def process_one(
    work: dict,
    oa_to_pid: dict,
    *,
    storage,
    cap_per_paper: int = 300,
    dry_run: bool = False,
) -> dict:
    hits = _hits(work, oa_to_pid)
    if not hits:
        return {"hits": 0, "applied": 0}
    citer = _citer_entry(work)
    updates: dict[str, list[dict]] = defaultdict(list)
    for _, pid in hits:
        updates[pid].append(citer)
    if dry_run:
        return {"hits": len(hits), "applied": 0}
    added = storage.batch_extend_external_cited_by(dict(updates), cap=cap_per_paper)
    return {"hits": len(hits), "applied": added}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    cap_per_paper: int = 300,
    checkpoint_root: Path | None = None,
) -> PhaseSummary:
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)
    oa_to_pid = storage.build_openalex_id_to_point_id_map()
    pending: dict[str, list[dict]] = defaultdict(list)
    files_done = 0
    current_file: str | None = None

    def _flush():
        if not pending:
            return
        if dry_run:
            pending.clear()
            return
        try:
            added = storage.batch_extend_external_cited_by(dict(pending), cap=cap_per_paper)
        except Exception as e:
            cp.write_failed_batch(PHASE, list(pending.items()), str(e), root=checkpoint_root)
            summary.failed_batches += 1
            pending.clear()
            return
        summary.applied += added
        pending.clear()

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                _flush()
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                files_done += 1
                if limit_files is not None and files_done >= limit_files:
                    current_file = None  # prevent post-loop double-mark/double-count
                    break
            current_file = fp
        summary.scanned += 1
        try:
            hits = _hits(work, oa_to_pid)
            if not hits:
                continue
            summary.matched += len(hits)
            citer = _citer_entry(work)
            for _, pid in hits:
                pending[pid].append(citer)
            if sum(len(v) for v in pending.values()) >= batch_size:
                _flush()
        except Exception as e:
            summary.worker_errors += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p4 worker error: %s", e)

    _flush()
    if current_file is not None:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        files_done += 1

    summary.duration_s = time.time() - t0
    summary.extra = {
        "files_done": files_done,
        "snapshot_extended_cited_by_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "cap_per_paper": cap_per_paper,
    }
    logger.info(summary.to_log_line())
    return summary
