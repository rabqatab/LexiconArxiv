"""P1: enrich-corpus-fields — fill missing metadata on every matched real paper."""
import logging
import time
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import work_source
from src.core.snapshot.extractor import extract_p1_fields
from src.core.snapshot.matcher import _norm_doi
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p1"


def _build_corpus_index(storage):
    """Return {doi: pid, openalex_id: pid, title_norm: pid} for matching."""
    doi_map: dict[str, str] = {}
    oa_map: dict[str, str] = {}
    title_map: dict[str, str] = {}
    for entry in storage.iter_all_real_papers_minimal():
        pid = entry["point_id"]
        if entry.get("doi"):
            doi_map.setdefault(entry["doi"], pid)
        if entry.get("openalex_id"):
            oa_map.setdefault(entry["openalex_id"], pid)
        if entry.get("title_norm"):
            title_map.setdefault(entry["title_norm"], pid)
    return doi_map, oa_map, title_map


def _match(work, doi_map, oa_map, title_map) -> str | None:
    """Return matched corpus point_id or None. DOI > OA > title (no corroboration here,
    since P1 only adds fields and never claims identity that affects ranking)."""
    if doi := _norm_doi(work.get("doi") or (work.get("ids") or {}).get("doi")):
        if pid := doi_map.get(doi):
            return pid
    if oa := (work.get("id") or "").rsplit("/", 1)[-1]:
        if pid := oa_map.get(oa):
            return pid
    # Title-only match without corroboration (P1 is metadata-safe; identity corroboration is P2)
    from src.core.deduplication import Deduplicator
    if title := work.get("title"):
        if tnorm := Deduplicator.normalize_title(title):
            if pid := title_map.get(tnorm):
                return pid
    return None


def process_one(work: dict, indexes, *, storage, dry_run: bool = False) -> dict:
    """Live-mode entry point: process a single work, return per-work summary dict."""
    doi_map, oa_map, title_map = indexes
    pid = _match(work, doi_map, oa_map, title_map)
    if pid is None:
        return {"matched": False, "applied": False}
    existing = storage.get_payload(pid) or {}
    fields = extract_p1_fields(work, existing_payload=existing)
    if not fields:
        return {"matched": True, "applied": False}
    if not dry_run:
        storage.batch_apply_field_fill([(pid, fields)])
    return {"matched": True, "applied": True, "fields": list(fields)}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    checkpoint_root: Path | None = None,
) -> PhaseSummary:
    """Stream the snapshot, fill missing metadata fields on matched corpus papers."""
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)
    indexes = _build_corpus_index(storage)
    pending: list[tuple[str, dict]] = []
    fields_counter: dict[str, int] = {}
    current_file: str | None = None
    files_done = 0

    def _flush():
        if not pending:
            return
        if not dry_run:
            try:
                storage.batch_apply_field_fill(pending)
            except Exception as e:
                cp.write_failed_batch(PHASE, pending, str(e), root=checkpoint_root)
                summary.failed_batches += 1
                pending.clear()
                return
            summary.applied += len(pending)
        pending.clear()

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                _flush()
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                files_done += 1
                if limit_files is not None and files_done >= limit_files:
                    break
            current_file = fp
        summary.scanned += 1
        try:
            doi_map, oa_map, title_map = indexes
            pid = _match(work, doi_map, oa_map, title_map)
            if pid is None:
                continue
            summary.matched += 1
            existing = storage.get_payload(pid) or {}
            fields = extract_p1_fields(work, existing_payload=existing)
            if not fields:
                continue
            for k in fields:
                fields_counter[k] = fields_counter.get(k, 0) + 1
            pending.append((pid, fields))
            if len(pending) >= batch_size:
                _flush()
        except Exception as e:
            summary.worker_errors += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p1 worker error: %s", e)

    _flush()
    if current_file is not None:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        files_done += 1

    summary.duration_s = time.time() - t0
    summary.extra = {
        "files_done": files_done,
        "fields_filled_by_name": fields_counter,
    }
    logger.info(summary.to_log_line())
    return summary
