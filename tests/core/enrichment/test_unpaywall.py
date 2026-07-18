"""Unit tests for Unpaywall OA-PDF parsing."""

from src.core.enrichment.unpaywall import parse_oa_pdf


def test_not_oa_returns_none():
    assert parse_oa_pdf({"is_oa": False, "best_oa_location": {"url_for_pdf": "x"}}) is None


def test_prefers_url_for_pdf():
    data = {"is_oa": True, "oa_status": "gold",
            "best_oa_location": {"url_for_pdf": "http://x/p.pdf", "url": "http://x/land"}}
    assert parse_oa_pdf(data) == ("http://x/p.pdf", "gold")


def test_falls_back_to_landing_url():
    data = {"is_oa": True, "oa_status": "green",
            "best_oa_location": {"url_for_pdf": None, "url": "http://x/land"}}
    assert parse_oa_pdf(data) == ("http://x/land", "green")


def test_oa_but_no_location_returns_none():
    assert parse_oa_pdf({"is_oa": True, "best_oa_location": None}) is None
    assert parse_oa_pdf({"is_oa": True, "best_oa_location": {}}) is None


def test_empty_returns_none():
    assert parse_oa_pdf({}) is None
