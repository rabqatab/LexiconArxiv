"""Yield work dicts from snapshot files (and, later, live API delta).

Phases consume `iter_snapshot_works` so they never see the file layout.
A later Plan 5 will add `iter_live_works` with the same yielded shape.
"""
import glob
import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path

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


def iter_live_works(*args, **kwargs):
    """Not implemented in Plan 1. Plan 5 will fetch /works?from_updated_date=..."""
    raise NotImplementedError("Live mode is delivered in Plan 5")
