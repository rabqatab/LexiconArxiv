from pathlib import Path

from src.core.snapshot import checkpoint as cp


def test_mark_done_then_load(tmp_path: Path):
    cp.mark_done("p1", "/snap/part_0001.gz", root=tmp_path)
    cp.mark_done("p1", "/snap/part_0002.gz", root=tmp_path)
    cp.mark_done("p1", "/snap/part_0001.gz", root=tmp_path)  # idempotent
    done = cp.load("p1", root=tmp_path)
    assert done == {"/snap/part_0001.gz", "/snap/part_0002.gz"}


def test_load_returns_empty_for_unknown_phase(tmp_path: Path):
    assert cp.load("p2", root=tmp_path) == set()


def test_write_failed_batch(tmp_path: Path):
    path = cp.write_failed_batch("p2", [{"a": 1}, {"a": 2}], "boom", root=tmp_path)
    assert path.exists()
    content = path.read_text().strip().splitlines()
    assert len(content) == 2


def test_quarantine(tmp_path: Path):
    p = cp.quarantine("p2", {"id": "w1", "title": "x"}, "verify failed", root=tmp_path)
    assert p.read_text().strip().endswith('"reason": "verify failed"}')


def test_live_high_water_mark(tmp_path: Path):
    assert cp.live_high_water_mark("p1", root=tmp_path) is None
    cp.set_live_high_water_mark("p1", "2026-06-20T12:00:00Z", root=tmp_path)
    assert cp.live_high_water_mark("p1", root=tmp_path) == "2026-06-20T12:00:00Z"


def test_reset_clears_phase(tmp_path: Path):
    cp.mark_done("p1", "/x.gz", root=tmp_path)
    cp.reset("p1", root=tmp_path)
    assert cp.load("p1", root=tmp_path) == set()


def test_reset_preserves_quarantine_audit_trail(tmp_path: Path):
    """reset() must not destroy the quarantine.jsonl audit log."""
    cp.mark_done("p2", "/x.gz", root=tmp_path)
    cp.quarantine("p2", {"id": "w1"}, "verify failed", root=tmp_path)
    quarantine_path = tmp_path / "p2" / "quarantine.jsonl"
    before = quarantine_path.read_text()
    cp.reset("p2", root=tmp_path)
    # done_files wiped...
    assert cp.load("p2", root=tmp_path) == set()
    # ...but quarantine survives byte-for-byte
    assert quarantine_path.exists()
    assert quarantine_path.read_text() == before
