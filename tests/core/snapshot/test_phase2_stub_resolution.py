from pathlib import Path

from src.core.snapshot import phase2_stub_resolution

FIX = Path(__file__).parent / "fixtures"


def _setup(tmp_path):
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    (d / "part_0000.gz").write_bytes((FIX / "works" / "tiny.jsonl.gz").read_bytes())
    return tmp_path / "data" / "works"


def test_p2_run_promotes_stubs_and_queues_embedding(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)
    cpt = tmp_path / "checkpoints"

    summary = phase2_stub_resolution.run(
        mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt,
    )

    # Expect: work 4 → promote stub-doi-001, work 5 → promote stub-title-001,
    # work 6 → ENRICH_KEEP_STUB on stub-doi-002.
    assert summary.extra["promoted"] >= 2
    assert summary.extra["enriched"] >= 1
    p = mock_storage.get_paper_by_id("stub-doi-001")
    assert p["is_stub"] is False
    assert "cited_by" in p


def test_p2_run_dry_run_no_mutation(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)

    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    summary = phase2_stub_resolution.run(
        mock_storage, snapshot_dir=str(snap), dry_run=True,
        checkpoint_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after
    # Dry-run still reports what would happen
    assert summary.extra.get("promoted", 0) >= 2


def test_p2_run_resume_skips_done_files(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)
    cpt = tmp_path / "checkpoints"

    s1 = phase2_stub_resolution.run(mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt)
    s2 = phase2_stub_resolution.run(mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt)
    assert s2.scanned == 0
