from pathlib import Path

from src.core.snapshot import phase3_gap_discovery
from src.core.snapshot import embedding_queue

FIX = Path(__file__).parent / "fixtures"


def _setup(tmp_path):
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    (d / "part_0000.gz").write_bytes((FIX / "works" / "tiny.jsonl.gz").read_bytes())
    return tmp_path / "data" / "works"


def test_p3_injects_anchor_and_concept_gaps(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    # Work 7 (W1000000008) is the anchor; work 8 + 9 are concept-passes.
    assert summary.extra["anchor_inject"] >= 1
    assert summary.extra["concept_inject"] >= 1
    assert summary.extra["rejected"] >= 1
    # Injection appears in mock storage
    assert any(pl.get("injected_from_snapshot") for _, pl in mock_storage.scroll_payloads())


def test_p3_max_injections_caps(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), max_injections=1, now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    assert summary.extra["anchor_inject"] + summary.extra["concept_inject"] == 1
    assert summary.extra["capped"] is True


def test_p3_dry_run_does_not_mutate(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), dry_run=True, now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after


def test_p3_skips_already_in_corpus(mock_storage, tmp_path):
    """If we already have a real paper with the same openalex_id, skip it."""
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    # Plant the anchor work as an existing real paper
    mock_storage.set_payload("real-anchor", {
        "is_stub": False, "openalex_id": "W1000000008", "title": "anchor",
    })
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    # anchor inject must NOT happen — W1000000008 already in corpus
    assert summary.extra["anchor_inject"] == 0
