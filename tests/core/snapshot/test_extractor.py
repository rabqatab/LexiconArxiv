import json
from pathlib import Path
import gzip

from src.core.snapshot.extractor import extract_p1_fields, extract_full_record

FIXTURE = Path(__file__).parent / "fixtures" / "works" / "tiny.jsonl.gz"


def _load_work(line_idx: int) -> dict:
    with gzip.open(FIXTURE, "rt") as f:
        for i, line in enumerate(f):
            if i == line_idx and line.strip():
                return json.loads(line)
    raise AssertionError(f"no work at line {line_idx}")


def test_extract_p1_returns_all_metric_fields_when_missing():
    work = _load_work(0)  # DOI-Match Corpus Paper
    out = extract_p1_fields(work, existing_payload={})
    assert out["cited_by_count"] == 42
    assert out["fwci"] == 1.4
    assert out["citation_normalized_percentile"] == {"value": 0.88}
    assert out["concepts"]
    assert out["best_oa_pdf_url"] == "https://example.com/best.pdf"
    assert out["orcid_map"] == {"Alice Researcher": "https://orcid.org/0000-0000-0000-0001"}


def test_extract_p1_skips_already_present():
    work = _load_work(0)
    out = extract_p1_fields(work, existing_payload={"cited_by_count": 9, "fwci": 0.1})
    assert "cited_by_count" not in out
    assert "fwci" not in out
    assert "concepts" in out  # still missing


def test_extract_p1_handles_missing_keys():
    out = extract_p1_fields({}, existing_payload={})
    assert out == {}


def test_extract_p1_skips_falsy_but_distinguishes_zero_from_none():
    # cited_by_count=0 is a real value; should be emitted as 0 if missing
    work = {"cited_by_count": 0, "fwci": None}
    out = extract_p1_fields(work, existing_payload={})
    assert out["cited_by_count"] == 0
    assert "fwci" not in out  # None means OpenAlex doesn't have it


def test_extract_full_record_has_core_keys():
    work = _load_work(0)
    out = extract_full_record(work)
    assert out["title"] == "DOI-Match Corpus Paper"
    assert out["doi"] == "10.1000/seed-doi-001"
    assert out["openalex_id"] == "W1000000001"
    assert out["year"] == 2024
    assert out["abstract"].startswith("This is an abstract")
    assert out["authors"] == [{"display_name": "Alice Researcher"}]
    assert out["referenced_works"] == ["https://openalex.org/W9999999991", "https://openalex.org/W1000000008"]
    # P1 fields are folded in
    assert out["cited_by_count"] == 42


def test_extract_full_record_missing_abstract_inverted_index():
    work = _load_work(6)  # Stub Partial — abstract_inverted_index is {}
    out = extract_full_record(work)
    assert out.get("abstract") in (None, "")
