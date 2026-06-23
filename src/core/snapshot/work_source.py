"""Yield work dicts from snapshot files (and, later, live API delta).

Phases consume `iter_snapshot_works` so they never see the file layout.
A later Plan 5 will add `iter_live_works` with the same yielded shape.
"""
import glob
import gzip
import json
import logging
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def iter_snapshot_works(
    snapshot_dir: str,
    *,
    skip_files: set[str] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield (filepath, work_dict) from `{snapshot_dir}/updated_date=*/*.gz` in sorted order."""
    skip = skip_files or set()
    files = sorted(glob.glob(str(Path(snapshot_dir) / "updated_date=*" / "*.gz")))
    for path in files:
        # Resolve both sides of the comparison so symlinked snapshot dirs (e.g. NFS)
        # produce stable checkpoint membership across runs.
        resolved = str(Path(path).resolve())
        if resolved in skip:
            continue
        try:
            with gzip.open(path, "rt") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield resolved, json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            # corrupt or unreadable .gz — skip this file but log so the operator
            # notices instead of only seeing a quiet "scanned" gap in counters.
            logger.warning("snapshot file unreadable (skipping): %s — %s", path, e)
            continue


def iter_live_works(
    *,
    since: date,
    mailto: str | None = None,
    per_page: int = 200,
    base_url: str = "https://api.openalex.org",
    timeout: float = 60.0,
) -> Iterator[dict]:
    """Yield work dicts from OpenAlex /works filtered by from_updated_date:<since>.

    Uses cursor pagination (per OpenAlex docs); each yielded dict has the same
    shape as a snapshot JSONL line. Passes `mailto` (default from OPENALEX_EMAIL
    env var) for the polite-pool rate limit.
    """
    mailto = mailto or os.environ.get("OPENALEX_EMAIL")
    params: dict[str, str | int] = {
        "filter": f"from_updated_date:{since.isoformat()}",
        "per-page": str(per_page),
        "cursor": "*",
    }
    if mailto:
        params["mailto"] = mailto
    with httpx.Client(timeout=timeout, base_url=base_url) as client:
        while True:
            r = client.get("/works", params=params)
            r.raise_for_status()
            payload = r.json()
            for w in payload.get("results") or []:
                yield w
            nxt = (payload.get("meta") or {}).get("next_cursor")
            if not nxt:
                return
            params["cursor"] = nxt
