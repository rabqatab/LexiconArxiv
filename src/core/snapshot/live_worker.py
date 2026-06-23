"""Live-mode wrapper: drives daily OpenAlex API delta through the P1→P2→P3→P4
process_one chain. Same phase logic as the snapshot bootstrap; only the work
source differs."""
import logging
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.core.snapshot import (
    checkpoint as cp,
    embedding_queue,
    phase1_corpus_fields,
    phase2_stub_resolution,
    phase3_gap_discovery,
    phase4_cited_by,
)
from src.core.snapshot.gap_filter import Thresholds
from src.core.snapshot.matcher import build_stub_index
from src.core.snapshot.work_source import iter_live_works

logger = logging.getLogger(__name__)

_PHASES = ("p1", "p2", "p3", "p4")


def _build_indexes(storage):
    """Build all four phase indexes once at the start of a live delta pass.

    For a single-digit-thousand work delta this is the right tradeoff — the
    indexes cost ~seconds to build but save N lookups per work."""
    # P1
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
    p1_indexes = (doi_map, oa_map, title_map)
    # P2
    stubs = list(storage.iter_stubs_for_resolution())
    stub_index = build_stub_index(stubs)
    all_stubs_by_id = {s["point_id"]: s for s in stubs}
    # P3
    dedup_idx = storage.build_identifier_index_for_dedup()
    anchor_set = storage.build_referenced_openalex_id_set()
    # P4
    oa_to_pid = storage.build_openalex_id_to_point_id_map()
    return p1_indexes, (stub_index, all_stubs_by_id), (dedup_idx, anchor_set), oa_to_pid


def run_live_delta(
    storage,
    *,
    since: date | None = None,
    days_back: int = 1,
    dry_run: bool = False,
    thresholds: Thresholds | None = None,
    max_injections: int | None = None,
    cap_per_paper: int = 300,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
    work_iterator=None,
) -> dict:
    """Single live-mode pass: fetch yesterday's API delta and run each work
    through all four phases. Idempotent — re-running the same since-date is safe
    (each phase is fill-only-missing / dedup-guarded)."""
    t0 = time.time()
    if since is None:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days_back))
    thresholds = thresholds or Thresholds()
    now_year = datetime.now(timezone.utc).year

    p1_indexes, (stub_index, all_stubs_by_id), (dedup_idx, anchor_set), oa_to_pid = \
        _build_indexes(storage)

    works = work_iterator if work_iterator is not None else iter_live_works(since=since)

    counters: dict[str, Counter] = {p: Counter() for p in _PHASES}
    fetched = 0
    injection_count = 0

    for work in works:
        fetched += 1
        try:
            # P1: corpus metadata fill
            r1 = phase1_corpus_fields.process_one(
                work, p1_indexes, storage=storage, dry_run=dry_run,
            )
            counters["p1"][r1.get("action") or ("matched" if r1.get("matched") else "no_match")] += 1
            if r1.get("matched"):
                counters["p1"]["matched"] += 1
            # P2: stub resolution
            r2 = phase2_stub_resolution.process_one(
                work, stub_index, all_stubs_by_id, storage=storage,
                dry_run=dry_run, embedding_queue_root=embedding_queue_root,
            )
            counters["p2"][r2.get("action") or "skip"] += 1
            # P3: gap discovery + injection
            r3 = phase3_gap_discovery.process_one(
                work, dedup_idx, anchor_set, storage=storage,
                thresholds=thresholds, now_year=now_year, dry_run=dry_run,
                embedding_queue_root=embedding_queue_root,
            )
            action3 = r3.get("action") or "skip"
            counters["p3"][action3] += 1
            cls = r3.get("classification")
            if cls == "ANCHOR_INJECT":
                counters["p3"]["anchor_inject"] += 1
            elif cls == "CONCEPT_INJECT":
                counters["p3"]["concept_inject"] += 1
            if action3 == "created":
                injection_count += 1
                if max_injections is not None and injection_count >= max_injections:
                    logger.warning("live-delta: hit max_injections=%d, stopping early",
                                   max_injections)
                    break
            # P4: external_cited_by extension (refs in this work that hit the corpus)
            r4 = phase4_cited_by.process_one(
                work, oa_to_pid, storage=storage,
                cap_per_paper=cap_per_paper, dry_run=dry_run,
            )
            counters["p4"]["hits"] += r4.get("hits", 0)
            counters["p4"]["applied"] += r4.get("applied", 0)
        except Exception as e:
            counters["meta"] = counters.get("meta", Counter())
            counters["meta"]["worker_errors"] += 1
            if counters["meta"]["worker_errors"] % 100 == 1:
                logger.warning("live-delta worker error: %s", e)

    # Update HWMs for all four phases at the end of a successful pass
    hwm_iso = since.isoformat()
    if not dry_run:
        for ph in _PHASES:
            cp.set_live_high_water_mark(ph, hwm_iso, root=checkpoint_root)

    summary = {
        "since": hwm_iso,
        "fetched": fetched,
        "per_phase": {p: dict(counters[p]) for p in _PHASES},
        "queue_depth_after": embedding_queue.depth(root=embedding_queue_root),
        "hwm_updated": {p: hwm_iso for p in _PHASES} if not dry_run
                       else {p: cp.live_high_water_mark(p, root=checkpoint_root) for p in _PHASES},
        "duration_s": round(time.time() - t0, 2),
        "dry_run": dry_run,
    }
    logger.info("live-delta: %s", summary)
    return summary
