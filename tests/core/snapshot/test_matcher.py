from src.core.crawler.openalex import reconstruct_abstract


def test_reconstruct_abstract_from_inverted_index():
    inv = {"Hello": [0], "world": [1], "foo": [2]}
    assert reconstruct_abstract(inv) == "Hello world foo"


def test_reconstruct_abstract_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


from src.core.snapshot.matcher import (
    Candidate, build_candidate_index, match_work, extract_enrichment,
)


def _cands():
    return [
        {"point_id": "d1", "doi": "10.1/x", "title": "Deep Nets", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False},
        {"point_id": "t1", "doi": None, "title": "Graph Models", "year": 2021,
         "first_author": "lee", "missing_abstract": True, "missing_refs": True},
    ]


def test_doi_match_is_trusted():
    doi_map, title_map = build_candidate_index(_cands())
    work = {"doi": "https://doi.org/10.1/x", "title": "totally different",
            "publication_year": 1900, "authorships": []}
    m = match_work(work, doi_map, title_map)
    assert m is not None and m.candidate.point_id == "d1" and m.source == "doi"


def test_title_match_requires_corroboration_year():
    doi_map, title_map = build_candidate_index(_cands())
    # same normalized title, year within +/-1 -> accept
    work = {"doi": None, "title": "Graph Models", "publication_year": 2021,
            "authorships": [{"author": {"display_name": "K. Park"}}]}
    m = match_work(work, doi_map, title_map)
    assert m is not None and m.candidate.point_id == "t1" and m.source == "title"


def test_title_match_rejected_without_corroboration():
    doi_map, title_map = build_candidate_index(_cands())
    # same title but year far off AND different author -> reject
    work = {"doi": None, "title": "Graph Models", "publication_year": 2005,
            "authorships": [{"author": {"display_name": "Q. Zhang"}}]}
    assert match_work(work, doi_map, title_map) is None


def test_extract_enrichment_fill_flags():
    cand = Candidate("t1", 2021, "lee", missing_abstract=True, missing_refs=True)
    work = {"abstract_inverted_index": {"Hi": [0], "there": [1]},
            "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"]}
    out = extract_enrichment(work, cand)
    assert out["abstract"] == "Hi there"
    assert out["referenced_works"] == ["https://openalex.org/W1", "https://openalex.org/W2"]


def test_title_match_corroborated_by_author_only():
    # year far off, but first-author surname matches -> accept
    doi_map, title_map = build_candidate_index(_cands())
    work = {"doi": None, "title": "Graph Models", "publication_year": 1990,
            "authorships": [{"author": {"display_name": "A. Lee"}}]}
    m = match_work(work, doi_map, title_map)
    assert m is not None and m.candidate.point_id == "t1" and m.source == "title"
