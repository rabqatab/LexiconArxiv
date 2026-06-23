from datetime import date
from pathlib import Path
import json

from src.core.snapshot import live_worker

FIX = Path(__file__).parent / "fixtures"


def _load_tiny_works():
    """Read the 12 valid lines from the existing tiny.jsonl.gz fixture."""
    import gzip
    out = []
    with gzip.open(FIX / "works" / "tiny.jsonl.gz", "rt") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def test_run_live_delta_chains_all_four_phases(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    works = _load_tiny_works()

    out = live_worker.run_live_delta(
        mock_storage,
        since=date(2026, 6, 22),
        work_iterator=iter(works),
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )

    # Aggregated summary keys
    assert out["fetched"] == len(works)
    for p in ("p1", "p2", "p3", "p4"):
        assert p in out["per_phase"]
        assert out["hwm_updated"][p] == "2026-06-22"

    # The tiny fixture provided: P1 matches (works 0, 1), P2 promotes some stubs,
    # P3 anchor+concept inject some, P4 hits some external citers. Just assert
    # at least one phase did something — the per-phase logic is unit-tested in
    # plans 2/3/4.
    total_activity = (
        out["per_phase"]["p1"].get("matched", 0)
        + out["per_phase"]["p2"].get("promoted", 0)
        + out["per_phase"]["p3"].get("anchor_inject", 0)
        + out["per_phase"]["p3"].get("concept_inject", 0)
    )
    assert total_activity > 0


def test_run_live_delta_dry_run_does_not_mutate(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    works = _load_tiny_works()

    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    out = live_worker.run_live_delta(
        mock_storage,
        since=date(2026, 6, 22),
        dry_run=True,
        work_iterator=iter(works),
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after
    assert out["fetched"] == len(works)


def test_run_live_delta_uses_default_iterator_when_not_injected(monkeypatch, mock_storage, tmp_path):
    """If work_iterator is None, run_live_delta computes since and calls iter_live_works."""
    called_with = {}

    def fake_iter(*, since, **_):
        called_with["since"] = since
        return iter([])

    from src.core.snapshot import live_worker as lw
    monkeypatch.setattr(lw, "iter_live_works", fake_iter)

    out = lw.run_live_delta(
        mock_storage,
        # since omitted → derived from days_back
        days_back=2,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    assert called_with["since"].isoformat()  # got a date
    assert out["fetched"] == 0


def test_run_live_delta_p1_matched_counted_once(mock_storage, tmp_path):
    """P1 matched works should be counted exactly once, not double-counted."""
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")

    # Load tiny works and feed only the first one (which matches in P1)
    works = _load_tiny_works()
    work_0 = works[0] if works else None

    if work_0 is not None:
        out = live_worker.run_live_delta(
            mock_storage,
            since=date(2026, 6, 22),
            work_iterator=iter([work_0]),
            checkpoint_root=tmp_path / "checkpoints",
            embedding_queue_root=tmp_path / "checkpoints",
        )

        # Assert matched count is exactly 1, not 2
        assert out["per_phase"]["p1"]["matched"] == 1


def test_run_live_delta_summary_includes_worker_errors(mock_storage, tmp_path):
    """Summary dict should include worker_errors at top level."""
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    works = _load_tiny_works()

    out = live_worker.run_live_delta(
        mock_storage,
        since=date(2026, 6, 22),
        work_iterator=iter(works),
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )

    # Assert worker_errors is present in summary (can be 0 if no errors occurred)
    assert "worker_errors" in out
    assert out["worker_errors"] >= 0
    assert out["fetched"] == len(works)
