from pathlib import Path
import json

import pytest

from src.core.snapshot import phase1_corpus_fields

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _setup_snapshot(tmp_path: Path) -> Path:
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    src = FIXTURE_DIR / "works" / "tiny.jsonl.gz"
    (d / "part_0000.gz").write_bytes(src.read_bytes())
    return tmp_path / "data" / "works"


def test_p1_run_fills_metadata_on_matched_corpus_papers(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIXTURE_DIR / "corpus" / "seed_papers.json")
    snap_dir = _setup_snapshot(tmp_path)

    summary = phase1_corpus_fields.run(
        mock_storage,
        snapshot_dir=str(snap_dir),
        checkpoint_root=tmp_path / "checkpoints",
    )

    # work 0 (DOI-Match) and work 1 (Title-Match) both match seed real-001/-002.
    assert summary.matched >= 2
    assert summary.applied >= 2
    # real-001 should now have cited_by_count = 42 from the snapshot
    pl = mock_storage.get_payload("real-001")
    assert pl["cited_by_count"] == 42
    assert "snapshot_filled_at" in pl


def test_p1_run_is_idempotent(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIXTURE_DIR / "corpus" / "seed_papers.json")
    snap_dir = _setup_snapshot(tmp_path)
    cpt = tmp_path / "checkpoints"

    s1 = phase1_corpus_fields.run(mock_storage, snapshot_dir=str(snap_dir), checkpoint_root=cpt)
    s2 = phase1_corpus_fields.run(mock_storage, snapshot_dir=str(snap_dir), checkpoint_root=cpt)
    assert s2.scanned == 0   # checkpoint skipped the only file
    assert s2.applied == 0


def test_p1_dry_run_does_not_mutate(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIXTURE_DIR / "corpus" / "seed_papers.json")
    snap_dir = _setup_snapshot(tmp_path)

    before = dict(mock_storage.get_payload("real-001"))
    summary = phase1_corpus_fields.run(
        mock_storage,
        snapshot_dir=str(snap_dir),
        dry_run=True,
        checkpoint_root=tmp_path / "checkpoints",
    )
    after = mock_storage.get_payload("real-001")
    assert summary.matched >= 2
    assert summary.applied == 0     # dry-run reports matched but applies nothing
    assert before == after


def test_p1_limit_files_does_not_double_count(mock_storage, tmp_path):
    """Regression: when limit_files triggers break, post-loop tail must not re-mark/count."""
    mock_storage.seed_from_json(FIXTURE_DIR / "corpus" / "seed_papers.json")
    # Two files so the limit can engage mid-stream
    d = tmp_path / "data" / "works"
    (d / "updated_date=2024-01-01").mkdir(parents=True)
    (d / "updated_date=2024-01-02").mkdir(parents=True)
    src = (FIXTURE_DIR / "works" / "tiny.jsonl.gz").read_bytes()
    (d / "updated_date=2024-01-01" / "part_0000.gz").write_bytes(src)
    (d / "updated_date=2024-01-02" / "part_0000.gz").write_bytes(src)

    summary = phase1_corpus_fields.run(
        mock_storage, snapshot_dir=str(d), limit_files=1,
        checkpoint_root=tmp_path / "checkpoints",
    )
    assert summary.extra["files_done"] == 1   # NOT 2 (pre-fix it would be 2)
