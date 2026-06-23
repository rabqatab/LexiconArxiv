"""P3: discover-corpus-gaps — inject hybrid-classified missing works as new real papers."""
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import embedding_queue
from src.core.snapshot import work_source
from src.core.snapshot.extractor import extract_full_record
from src.core.snapshot.gap_filter import (
    AI_CONCEPT_IDS,
    Classification,
    Thresholds,
    classify,
)
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p3"


def _wid(work: dict) -> str:
    return (work.get("id") or "").rsplit("/", 1)[-1]


def _already_in_corpus(work: dict, dedup_idx: dict[str, set[str]]) -> bool:
    wid = _wid(work)
    if wid and wid in dedup_idx["openalex_id"]:
        return True
    from src.core.snapshot.extractor import _norm_doi
    doi = _norm_doi(work.get("doi"))
    if doi and doi in dedup_idx["doi"]:
        return True
    return False


def process_one(
    work,
    dedup_idx,
    anchor_set,
    *,
    storage,
    thresholds: Thresholds,
    now_year: int,
    dry_run: bool = False,
    embedding_queue_root: Path | None = None,
) -> dict:
    if _already_in_corpus(work, dedup_idx):
        return {"action": "skip_existing"}

    cls = classify(work, anchor_set=anchor_set, taxonomy=AI_CONCEPT_IDS,
                   thresholds=thresholds, now_year=now_year)
    if cls is Classification.REJECT:
        return {"action": "reject"}

    if dry_run:
        return {"action": "would_inject", "classification": cls.value}

    fields = extract_full_record(work)
    if not fields.get("openalex_id"):
        return {"action": "no_oa_id"}
    result = storage.batch_inject_papers([{
        "openalex_id": fields["openalex_id"],
        "work_fields": fields,
        "injection_path": "anchor" if cls is Classification.ANCHOR_INJECT else "concept",
    }])
    r = result[0]
    if r["status"] == "created":
        # update in-process dedup index so a same-pass duplicate is caught
        dedup_idx["openalex_id"].add(fields["openalex_id"])
        if fields.get("abstract") and r.get("point_id"):
            embedding_queue.append(r["point_id"], source="injection",
                                   root=embedding_queue_root)
    return {"action": r["status"], "classification": cls.value,
            "point_id": r.get("point_id")}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    max_injections: int | None = None,
    thresholds: Thresholds | None = None,
    now_year: int | None = None,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
) -> PhaseSummary:
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)
    thresholds = thresholds or Thresholds()
    now_year = now_year or datetime.now(timezone.utc).year

    dedup_idx = storage.build_identifier_index_for_dedup()
    anchor_set = storage.build_referenced_openalex_id_set()

    counters = Counter()
    year_counter = Counter()
    concept_counter = Counter()
    current_file: str | None = None
    files_done = 0
    capped = False

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                files_done += 1
                if limit_files is not None and files_done >= limit_files:
                    break
            current_file = fp
        summary.scanned += 1
        try:
            res = process_one(
                work, dedup_idx, anchor_set,
                storage=storage, thresholds=thresholds, now_year=now_year,
                dry_run=dry_run, embedding_queue_root=embedding_queue_root,
            )
            action = res.get("action")
            cls = res.get("classification")

            if action == "skip_existing":
                counters["skip_existing"] += 1
            elif action == "reject":
                counters["rejected"] += 1
            elif action == "created" or action == "would_inject":
                if cls == "ANCHOR_INJECT":
                    counters["anchor_inject"] += 1
                else:
                    counters["concept_inject"] += 1
                if year := work.get("publication_year"):
                    year_counter[year] += 1
                for c in work.get("concepts") or []:
                    cid = (c.get("id") or "").rsplit("/", 1)[-1]
                    if cid and cid in AI_CONCEPT_IDS:
                        concept_counter[c.get("display_name") or cid] += 1
                if action == "created":
                    summary.applied += 1
                total_inject = counters["anchor_inject"] + counters["concept_inject"]
                if max_injections is not None and total_inject >= max_injections:
                    capped = True
                    break
            elif action in ("skipped_dup", "failed", "no_oa_id"):
                counters[action] += 1
        except Exception as e:
            summary.worker_errors += 1
            cp.quarantine(PHASE, work, str(e), root=checkpoint_root)
            summary.quarantined += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p3 worker error: %s", e)

    if current_file is not None and not capped:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        files_done += 1

    summary.matched = counters["anchor_inject"] + counters["concept_inject"]
    summary.duration_s = time.time() - t0
    summary.extra = {
        "files_done": files_done,
        "anchor_inject": counters["anchor_inject"],
        "concept_inject": counters["concept_inject"],
        "rejected": counters["rejected"],
        "skip_existing": counters["skip_existing"],
        "skipped_dup": counters["skipped_dup"],
        "failed": counters["failed"],
        "no_oa_id": counters["no_oa_id"],
        "queued_for_embed": summary.applied,
        "year_distribution": dict(year_counter.most_common(20)),
        "top_concepts": dict(concept_counter.most_common(10)),
        "capped": capped,
    }
    logger.info(summary.to_log_line())
    return summary
