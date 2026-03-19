"""Tests for MCP formatters."""

import pytest

from src.mcp.formatters import format_paper_detail, format_search_results


class TestFormatSearchResults:
    """Tests for format_search_results."""

    def test_basic_formatting(self):
        results = {
            "results": [
                {
                    "id": "abc-123",
                    "title": "Attention Is All You Need",
                    "authors": ["Vaswani", "Shazeer", "Parmar"],
                    "venue": "NeurIPS",
                    "year": 2017,
                    "tier": 0,
                    "citation_count": 50000,
                    "keywords": ["attention", "transformer"],
                    "score": 0.95,
                },
            ],
            "total": 1,
            "query_time_ms": 42,
            "search_mode": "hybrid",
        }
        text = format_search_results(results)
        assert "Attention Is All You Need" in text
        assert "Vaswani" in text
        assert "Shazeer" in text
        assert "NeurIPS" in text
        assert "50000" in text
        assert "attention" in text
        assert "0.95" in text
        assert "hybrid" in text

    def test_empty_results(self):
        results = {"results": [], "total": 0, "query_time_ms": 5, "search_mode": "bm25_only"}
        text = format_search_results(results)
        assert "No results" in text

    def test_max_results_truncation(self):
        items = [
            {
                "id": f"id-{i}",
                "title": f"Paper {i}",
                "authors": [f"Author {i}"],
                "venue": "ICML",
                "year": 2023,
                "tier": 1,
                "citation_count": i * 10,
                "keywords": ["ml"],
                "score": 0.5,
            }
            for i in range(20)
        ]
        results = {"results": items, "total": 20, "query_time_ms": 10, "search_mode": "hybrid"}
        text = format_search_results(results, max_results=5)
        # Should include Paper 0 through Paper 4 but not Paper 5+
        assert "Paper 0" in text
        assert "Paper 4" in text
        assert "Paper 5" not in text

    def test_many_authors_truncation(self):
        results = {
            "results": [
                {
                    "id": "abc",
                    "title": "Multi-Author Paper",
                    "authors": ["A", "B", "C", "D", "E"],
                    "venue": "ACL",
                    "year": 2022,
                    "citation_count": 10,
                    "keywords": [],
                    "score": 0.8,
                },
            ],
            "total": 1,
            "query_time_ms": 5,
            "search_mode": "hybrid",
        }
        text = format_search_results(results)
        assert "A, B, C" in text
        assert "et al." in text
        assert "5 authors" in text

    def test_missing_optional_fields(self):
        results = {
            "results": [
                {
                    "id": "abc",
                    "title": "Minimal Paper",
                    "authors": [],
                    "citation_count": 0,
                    "keywords": [],
                    "score": 0.1,
                },
            ],
            "total": 1,
            "query_time_ms": 3,
            "search_mode": "bm25_only",
        }
        text = format_search_results(results)
        assert "Minimal Paper" in text
        assert "Citations: 0" in text


class TestFormatPaperDetail:
    """Tests for format_paper_detail."""

    def test_full_paper_detail(self):
        paper = {
            "id": "abc-123",
            "title": "Attention Is All You Need",
            "abstract": "The dominant sequence transduction models...",
            "authors": ["Vaswani", "Shazeer"],
            "venue": "NeurIPS",
            "year": 2017,
            "tier": 0,
            "doi": "10.5555/3295222.3295349",
            "arxiv_id": "1706.03762",
            "citation_count": 50000,
            "pagerank": 0.001234,
            "keywords": ["attention", "transformer"],
            "keywords_structured": {"Task": ["translation"], "Method": ["self-attention"]},
            "abstract_structure": {"Background": "Seq models...", "Method": "We propose..."},
            "code_repositories": [{"url": "https://github.com/tensorflow/tensor2tensor"}],
            "code_url": "https://github.com/tensorflow/tensor2tensor",
            "pdf_url": "https://arxiv.org/pdf/1706.03762",
            "is_core": True,
            "is_stub": False,
            "reference_count": 42,
            "cited_by_count": 1200,
        }
        text = format_paper_detail(paper)
        assert "# Attention Is All You Need" in text
        assert "Vaswani" in text
        assert "NeurIPS" in text
        assert "10.5555/3295222.3295349" in text
        assert "1706.03762" in text
        assert "50000" in text
        assert "PageRank" in text
        assert "attention" in text
        assert "transformer" in text
        assert "translation" in text
        assert "self-attention" in text
        assert "Seq models" in text
        assert "We propose" in text
        assert "tensor2tensor" in text
        assert "Core" in text
        assert "References: 42" in text
        assert "Cited by: 1200" in text

    def test_empty_paper(self):
        text = format_paper_detail({})
        assert "Untitled" in text

    def test_none_paper(self):
        text = format_paper_detail(None)
        assert "not found" in text

    def test_stub_paper(self):
        paper = {
            "id": "stub-123",
            "title": "Some Stub Paper",
            "authors": [],
            "is_stub": True,
            "is_core": False,
            "citation_count": 0,
            "reference_count": 0,
            "cited_by_count": 0,
        }
        text = format_paper_detail(paper)
        assert "Stub" in text
        assert "Core" not in text.split("Stub")[0]  # "Core" should not appear before "Stub"

    def test_paper_with_code_url_only(self):
        paper = {
            "id": "code-123",
            "title": "Paper With Code URL",
            "authors": ["Author"],
            "code_url": "https://github.com/example/repo",
            "code_repositories": [],
            "citation_count": 5,
            "reference_count": 0,
            "cited_by_count": 0,
        }
        text = format_paper_detail(paper)
        assert "https://github.com/example/repo" in text
