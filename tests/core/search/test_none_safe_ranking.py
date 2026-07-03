"""Regression for 2026-07-03 incident: search endpoints failed with
'unsupported operand type(s) for +: int and NoneType' because P2 promotion
writes payloads where numeric fields can be `None` (not missing). Every
ranking pass must treat `None` numeric fields as 0."""

from src.core.search.postprocess import apply_citation_boost


def test_apply_citation_boost_handles_none_citation_count():
    """A paper with citation_count=None must not crash the ranking."""
    results = [
        {"id": "a", "score": 0.9, "citation_count": None, "pagerank": 0.5},
        {"id": "b", "score": 0.8, "citation_count": 42, "pagerank": None},
        {"id": "c", "score": 0.7, "citation_count": None, "pagerank": None},
    ]
    out = apply_citation_boost(list(results))
    # All three papers ranked without exception
    assert len(out) == 3
    assert all("score" in r for r in out)
    # None was treated as 0 — paper b (citation_count=42) should outrank c
    ids = [r["id"] for r in out]
    assert ids.index("b") < ids.index("c")


def test_apply_citation_boost_handles_none_score():
    """A paper with score=None must not crash the ranking."""
    results = [
        {"id": "a", "score": None, "citation_count": 10, "pagerank": 0.5},
        {"id": "b", "score": 0.8, "citation_count": 5, "pagerank": 0.5},
    ]
    out = apply_citation_boost(list(results))
    assert len(out) == 2
    assert all(isinstance(r["score"], (int, float)) for r in out)


def test_apply_citation_boost_all_none_does_not_crash():
    """Extreme case: every numeric field is None — must degrade to score=0 not raise."""
    results = [
        {"id": "a", "score": None, "citation_count": None, "pagerank": None},
        {"id": "b", "score": None, "citation_count": None, "pagerank": None},
    ]
    out = apply_citation_boost(list(results))
    assert len(out) == 2
    for r in out:
        assert isinstance(r["score"], (int, float))
        # With all inputs None -> 0, score should be 0 (or very close)
        assert r["score"] == 0.0
