"""Unit tests for external-API parsers/converters (no network)."""

from src.core.external.dblp import parse_dblp_hits, _authors
from src.core.external.opencitations import _extract_ids, parse_citations
from src.core.external.core_api import parse_core_results
from src.core.external.zotero import paper_to_zotero_item, _creators


# --- DBLP ---

def test_dblp_authors_list_and_single():
    assert _authors({"authors": {"author": [{"text": "A B"}, {"text": "C D"}]}}) == ["A B", "C D"]
    # DBLP returns a dict (not list) for a single author
    assert _authors({"authors": {"author": {"text": "Solo Author"}}}) == ["Solo Author"]
    assert _authors({}) == []


def test_dblp_parse_hits_strips_dot_and_skips_titleless():
    data = {"result": {"hits": {"hit": [
        {"info": {"title": "Attention Is All You Need.", "year": "2017",
                  "venue": "NeurIPS", "doi": "10.x/y",
                  "authors": {"author": {"text": "A Vaswani"}}}},
        {"info": {"year": "2020"}},  # no title → skipped
    ]}}}
    rows = parse_dblp_hits(data)
    assert len(rows) == 1
    assert rows[0]["title"] == "Attention Is All You Need"  # trailing dot stripped
    assert rows[0]["year"] == 2017 and rows[0]["doi"] == "10.x/y"


def test_dblp_empty_response():
    assert parse_dblp_hits({}) == []


# --- OpenCitations ---

def test_oc_extract_ids():
    f = "omid:br/06410146334 doi:10.3897/rio.9.e94851 openalex:W4322632649"
    assert _extract_ids(f) == {"doi": "10.3897/rio.9.e94851", "openalex": "W4322632649"}
    assert _extract_ids("") == {}


def test_oc_parse_citations():
    data = [{"citing": "doi:10.1/a openalex:W1", "cited": "doi:10.2/b", "creation": "2023-03-01"}]
    rows = parse_citations(data, key="citing")
    assert rows == [{"doi": "10.1/a", "openalex": "W1", "creation": "2023-03-01"}]


# --- CORE ---

def test_core_parse_results():
    data = {"results": [
        {"title": "Deep X", "authors": [{"name": "A B"}, {"name": "C D"}],
         "yearPublished": 2021, "doi": "10.z/w", "downloadUrl": "http://pdf",
         "abstract": "abs"},
        {"authors": []},  # no title → skipped
    ]}
    rows = parse_core_results(data)
    assert len(rows) == 1
    assert rows[0]["download_url"] == "http://pdf" and rows[0]["authors"] == ["A B", "C D"]


# --- Zotero ---

def test_zotero_creators_split_and_mononym():
    c = _creators(["Ashish Vaswani", "Cher"])
    assert c[0] == {"creatorType": "author", "firstName": "Ashish", "lastName": "Vaswani"}
    assert c[1] == {"creatorType": "author", "name": "Cher"}  # single token → single-field


def test_zotero_item_journal_vs_conference():
    j = paper_to_zotero_item({"title": "T", "venue": "JMLR", "year": 2020,
                              "authors": ["A B"], "doi": "10.1/x"})
    assert j["itemType"] == "journalArticle" and j["publicationTitle"] == "JMLR"
    assert j["DOI"] == "10.1/x" and j["date"] == "2020"

    c = paper_to_zotero_item({"title": "T", "venue": "NeurIPS Conference", "authors": []})
    assert c["itemType"] == "conferencePaper" and c["proceedingsTitle"] == "NeurIPS Conference"
