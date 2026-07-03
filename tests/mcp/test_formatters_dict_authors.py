"""Regression for 2026-07-03 incident: MCP formatters crashed with
'sequence item 0: expected str instance, dict found' because P2 promotion
writes OpenAlex `authorships` payloads (list of dicts) but the formatters
did `", ".join(authors)` assuming a list of strings."""

from src.mcp.formatters import (
    _author_name,
    format_paper_detail,
    format_research_results,
    format_search_results,
)


def test_author_name_accepts_string():
    assert _author_name("Jane Doe") == "Jane Doe"


def test_author_name_accepts_dict_with_display_name():
    assert _author_name({"display_name": "A. Vaswani"}) == "A. Vaswani"


def test_author_name_accepts_nested_openalex_authorship():
    """OpenAlex authorships shape: {'author': {'display_name': ...}, 'position': ...}"""
    entry = {"author": {"display_name": "N. Shazeer", "orcid": "..."}, "position": "middle"}
    assert _author_name(entry) == "N. Shazeer"


def test_author_name_handles_none_and_missing():
    assert _author_name(None) == ""
    assert _author_name({}) == ""
    assert _author_name({"unrelated_key": "x"}) == ""


def test_format_search_results_with_mixed_author_shapes_does_not_raise():
    """Direct reproduction of the incident: mix of dict + str authors."""
    results = {
        "results": [{
            "id": "p1",
            "title": "Attention Is All You Need",
            "authors": [
                {"display_name": "A. Vaswani"},
                {"display_name": "N. Shazeer"},
                "legacy string author",
            ],
            "venue": "NeurIPS",
            "year": 2017,
            "tier": 0,
            "citation_count": 100000,
            "score": 0.95,
        }],
        "total": 1, "query_time_ms": 5, "search_mode": "hybrid",
    }
    out = format_search_results(results)
    assert "Attention Is All You Need" in out
    assert "A. Vaswani" in out
    assert "N. Shazeer" in out
    assert "legacy string author" in out


def test_format_paper_detail_with_dict_authors_does_not_raise():
    paper = {
        "id": "p1", "title": "T",
        "authors": [{"display_name": "A. Vaswani"}, {"display_name": "N. Shazeer"}],
    }
    out = format_paper_detail(paper)
    assert "A. Vaswani" in out
    assert "N. Shazeer" in out


def test_format_paper_detail_with_empty_authors_skips_section():
    paper = {"id": "p1", "title": "T", "authors": []}
    out = format_paper_detail(paper)
    assert "**Authors:**" not in out


def test_format_paper_detail_with_all_unnamed_dict_authors_skips_section():
    """A list of dicts that ALL fail to yield a display name — must not print an empty Authors line."""
    paper = {"id": "p1", "title": "T", "authors": [{"orcid": "..."}, {"position": "first"}]}
    out = format_paper_detail(paper)
    # We do NOT want to print '**Authors:** ' with nothing after it
    assert "**Authors:** \n" not in out


def test_format_research_results_with_dict_authors_does_not_raise():
    """Regression for the 2026-07-03 State-4 report: research_topic raised
    'sequence item 0: expected str instance, dict found' because
    format_research_results still joined dict authors as strings."""
    data = {
        "query": "efficient markets return predictability",
        "papers": [{
            "id": "p1",
            "title": "Attention Is All You Need",
            "authors": [
                {"display_name": "A. Vaswani"},
                {"display_name": "N. Shazeer"},
                {"display_name": "N. Parmar"},
                {"display_name": "J. Uszkoreit"},  # >3 to exercise et-al path
            ],
            "venue": "NeurIPS", "year": 2017, "tier": 0,
            "citation_count": 100000,
            "relevance_score": 0.9, "notable_score": 0.85, "combined_score": 0.88,
            "keywords": ["attention", "transformer"],
        }],
        "trends": [{"keyword": "transformer", "growth_rate": 1.5}],
        "summary": {"total_found": 1},
        "query_time_ms": 12,
    }
    out = format_research_results(data)
    assert "Attention Is All You Need" in out
    assert "A. Vaswani" in out
    assert "N. Shazeer" in out
    assert "et al." in out
