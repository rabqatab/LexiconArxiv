"""P2: resolve-stubs-from-snapshot — match every stub, then promote/enrich/merge."""
import logging
import time
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import work_source
from src.core.snapshot.extractor import extract_full_record
from src.core.snapshot.matcher import build_stub_index, match_work_for_stubs
from src.core.snapshot.promotion import Decision, PromotionError, evaluate, promote_one
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p2"


def _gains_filter(stub: dict, fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if v in (None, "", [], {}):
            continue
        if stub.get(k):
            continue
        out[k] = v
    return out


def process_one(
    work,
    stub_index,
    all_stubs_by_id,
    *,
    storage,
    dry_run: bool = False,
    allow_promotion: bool = True,
    allow_merge: bool = True,
    embedding_queue_root: Path | None = None,
    min_cites_per_year: float = 0.0,
    now_year: int | None = None,
) -> dict:
    stub = match_work_for_stubs(work, stub_index, all_stubs_by_id=all_stubs_by_id)
    if stub is None:
        return {"matched": False, "action": None}

    fields = extract_full_record(work)
    decision = evaluate(stub, fields,
                        min_cites_per_year=min_cites_per_year,
                        now_year=now_year)

    if decision is Decision.SKIP:
        return {"matched": True, "action": "skip"}

    if dry_run:
        return {"matched": True, "action": decision.value, "would_promote": True}

    if decision is Decision.PROMOTE and allow_promotion:
        try:
            result = promote_one(storage, stub, fields,
                                 embedding_queue_root=embedding_queue_root,
                                 allow_merge=allow_merge)
        except PromotionError as e:
            return {"matched": True, "action": "promote_failed", "error": str(e)}
        if result is Decision.MERGED_INTO_EXISTING:
            if not allow_merge:
                return {"matched": True, "action": "merge_blocked"}
            return {"matched": True, "action": "merged"}
        return {"matched": True, "action": "promoted"}

    if decision is Decision.ENRICH_KEEP_STUB or decision is Decision.PROMOTE:
        # ENRICH_KEEP_STUB always; PROMOTE falls here only if allow_promotion=False
        gains = _gains_filter(stub, fields)
        if gains:
            storage.batch_apply_field_fill([(stub["point_id"], gains)])
        return {"matched": True, "action": "enriched", "field_count": len(gains)}

    return {"matched": True, "action": "skip"}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    allow_promotion: bool = True,
    allow_merge: bool = True,
    min_cites_per_year: float = 0.0,
    now_year: int | None = None,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
) -> PhaseSummary:
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)

    stubs = list(storage.iter_stubs_for_resolution())
    summary.extra["stubs_seen"] = len(stubs)
    stub_index = build_stub_index(stubs)
    all_stubs_by_id = {s["point_id"]: s for s in stubs}

    counters = {"promoted": 0, "enriched": 0, "merged": 0, "merge_blocked": 0,
                "promote_failed": 0, "skip": 0,
                "doi_matches": 0, "title_matches": 0, "openalex_matches": 0,
                "arxiv_matches": 0, "queued_for_embed": 0, "files_done": 0}
    current_file: str | None = None

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                counters["files_done"] += 1
                if limit_files is not None and counters["files_done"] >= limit_files:
                    break
            current_file = fp
        summary.scanned += 1
        try:
            res = process_one(
                work, stub_index, all_stubs_by_id,
                storage=storage, dry_run=dry_run,
                allow_promotion=allow_promotion, allow_merge=allow_merge,
                embedding_queue_root=embedding_queue_root,
                min_cites_per_year=min_cites_per_year,
                now_year=now_year,
            )
            if res.get("matched"):
                summary.matched += 1
                action = res.get("action")
                if dry_run and res.get("would_promote"):
                    # In dry_run, action is the Decision.value string (e.g. "PROMOTE").
                    # Map PROMOTE → promoted counter so dry-run reporting is consistent.
                    if action == Decision.PROMOTE.value:
                        counters["promoted"] += 1
                    elif action == Decision.ENRICH_KEEP_STUB.value:
                        counters["enriched"] += 1
                elif action in counters:
                    counters[action] += 1
                    if action == "promoted" and not dry_run:
                        counters["queued_for_embed"] += 1
        except Exception as e:
            summary.worker_errors += 1
            cp.quarantine(PHASE, work, str(e), root=checkpoint_root)
            summary.quarantined += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p2 worker error: %s", e)

    if current_file is not None:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        counters["files_done"] += 1

    summary.applied = counters["promoted"] + counters["enriched"] + counters["merged"]
    summary.duration_s = time.time() - t0
    summary.extra.update(counters)
    logger.info(summary.to_log_line())
    return summary
