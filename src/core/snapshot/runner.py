"""Streaming-join runner: enrich the corpus from a local OpenAlex works snapshot."""

import glob
import gzip
import json
import logging
import os

from src.core.snapshot.matcher import build_candidate_index, match_work, extract_enrichment

logger = logging.getLogger(__name__)


def _iter_work_files(snapshot_dir: str):
    # works/updated_date=*/*.gz
    pattern = os.path.join(snapshot_dir, "updated_date=*", "*.gz")
    return sorted(glob.glob(pattern))


def run_snapshot_enrichment(storage, snapshot_dir: str, dry_run: bool = False,
                            batch_size: int = 500) -> dict:
    """Stream the snapshot works files and fill-only-missing enrichment into Qdrant.

    Returns counts: scanned, doi_matches, title_matches, applied, candidates.
    """
    candidates = list(storage.iter_enrichment_candidates())
    doi_map, title_map = build_candidate_index(candidates)
    logger.info("Snapshot candidates: %d (doi=%d, title_norm=%d)",
                len(candidates), len(doi_map), len(title_map))

    scanned = doi_matches = title_matches = applied = 0
    seen_points: set[str] = set()
    pending: list[tuple[str, dict]] = []

    def flush():
        nonlocal applied, pending
        if pending and not dry_run:
            applied += storage.batch_apply_snapshot_enrichment(pending)
        pending = []

    for path in _iter_work_files(snapshot_dir):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    work = json.loads(line)
                except json.JSONDecodeError:
                    continue
                scanned += 1
                m = match_work(work, doi_map, title_map)
                if not m or m.candidate.point_id in seen_points:
                    continue
                fields = extract_enrichment(work, m.candidate)
                if not fields:
                    continue
                seen_points.add(m.candidate.point_id)
                if m.source == "doi":
                    doi_matches += 1
                else:
                    title_matches += 1
                pending.append((m.candidate.point_id, fields))
                if len(pending) >= batch_size:
                    flush()
        logger.info("Processed %s | scanned=%d matches=%d", os.path.basename(path),
                    scanned, doi_matches + title_matches)
    flush()
    return {"scanned": scanned, "doi_matches": doi_matches,
            "title_matches": title_matches, "applied": applied,
            "candidates": len(candidates)}
