from pathlib import Path
import gzip
import json

from src.core.snapshot.work_source import iter_snapshot_works

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "works"


def _setup_snapshot_layout(tmp_path: Path) -> Path:
    """Create a fake snapshot dir tree with one .gz file."""
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    src = FIXTURE_DIR / "tiny.jsonl.gz"
    (d / "part_0000.gz").write_bytes(src.read_bytes())
    return tmp_path / "data" / "works"


def test_iter_yields_works(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    works = list(iter_snapshot_works(str(snap)))
    # tiny.jsonl has 12 valid works + 2 invalid (blank + non-JSON)
    assert len(works) == 12
    paths = {p for p, _ in works}
    assert len(paths) == 1
    assert all(isinstance(w, dict) for _, w in works)


def test_iter_skips_done_files(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    done = {str((snap / "updated_date=2024-01-01" / "part_0000.gz").resolve())}
    works = list(iter_snapshot_works(str(snap), skip_files=done))
    assert works == []


def test_iter_skips_blank_and_malformed_lines(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    works = list(iter_snapshot_works(str(snap)))
    # The 2 noise lines must not appear
    assert all("title" in w or "doi" in w or "id" in w for _, w in works)
