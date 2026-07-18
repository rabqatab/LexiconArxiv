import gzip
import json
from pathlib import Path

from src.core.snapshot.matcher import build_stub_index, match_work_for_stubs

FIXTURE = Path(__file__).parent / "fixtures" / "works" / "tiny.jsonl.gz"
SEED_STUBS = Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json"


def _load_work(idx: int) -> dict:
    with gzip.open(FIXTURE, "rt") as f:
        for i, ln in enumerate(f):
            if i == idx and ln.strip():
                return json.loads(ln)
    raise AssertionError(idx)


def _load_stubs() -> list[dict]:
    raw = json.loads(SEED_STUBS.read_text())
    return [
        {"point_id": e["point_id"], **e["payload"]}
        for e in raw
    ]


def test_doi_stub_match():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(4)  # W1000000005 stub-doi-001
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is not None
    assert matched["point_id"] == "stub-doi-001"


def test_title_stub_match():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(5)  # W1000000006 Stub Title Match Promotable
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is not None
    assert matched["point_id"] == "stub-title-001"


def test_no_match_returns_none():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(7)  # W1000000008 Anchor Gap Paper — not a stub
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is None


def test_grobid_title_stub_from_identifier():
    # Real-corpus shape: `title` empty, raw title in identifier as "TITLE:<text>"
    # (751K GROBID reference stubs). These must be matchable from the identifier.
    stubs = [{
        "point_id": "stub-grobid-001",
        "identifier_type": "title",
        "identifier": "TITLE:beyond rankings comparing directed acyclic graphs",
        "title": None, "year": None, "authors": [],
    }]
    idx = build_stub_index(stubs)
    work = {"id": "https://openalex.org/W9",
            "title": "Beyond Rankings: Comparing Directed Acyclic Graphs"}
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is not None and matched["point_id"] == "stub-grobid-001"


def test_short_grobid_title_stub_not_indexed():
    # 4-word floor: a bare fragment must not collide with generic snapshot titles.
    stubs = [{"point_id": "stub-junk", "identifier_type": "title",
              "identifier": "TITLE:related work", "title": None,
              "year": None, "authors": []}]
    idx = build_stub_index(stubs)
    assert idx.title_map == {}
