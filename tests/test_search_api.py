"""Tests for search API endpoint validation."""

import pytest
from pydantic import ValidationError

from src.api.models.search import SearchRequest


class TestSearchValidation:
    """Test request validation for POST /api/search."""

    # --- Direct Pydantic model validation tests ---

    def test_empty_query_returns_422(self):
        """Empty query string should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest(query="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("query",) for e in errors)

    def test_missing_query_returns_422(self):
        """Missing query field should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest()
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("query",) for e in errors)

    def test_query_too_long_returns_422(self):
        """Query exceeding 500 characters should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest(query="a" * 501)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("query",) for e in errors)

    def test_limit_too_high_returns_422(self):
        """Limit above 100 should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest(query="test", limit=200)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("limit",) for e in errors)

    def test_limit_zero_returns_422(self):
        """Limit of 0 should fail validation (minimum is 1)."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest(query="test", limit=0)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("limit",) for e in errors)

    def test_negative_offset_returns_422(self):
        """Negative offset should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchRequest(query="test", offset=-1)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("offset",) for e in errors)

    # --- Valid request tests ---

    def test_valid_minimal_request(self):
        """Minimal valid request with just a query."""
        req = SearchRequest(query="attention mechanism")
        assert req.query == "attention mechanism"
        assert req.limit == 20
        assert req.offset == 0
        assert req.filters is None

    def test_valid_full_request(self):
        """Fully specified valid request."""
        req = SearchRequest(query="transformers", limit=50, offset=10)
        assert req.query == "transformers"
        assert req.limit == 50
        assert req.offset == 10

    def test_valid_boundary_limit(self):
        """Limit at maximum boundary (100) should be accepted."""
        req = SearchRequest(query="test", limit=100)
        assert req.limit == 100

    def test_valid_boundary_limit_min(self):
        """Limit at minimum boundary (1) should be accepted."""
        req = SearchRequest(query="test", limit=1)
        assert req.limit == 1

    def test_valid_boundary_query_max_length(self):
        """Query at exactly 500 characters should be accepted."""
        req = SearchRequest(query="a" * 500)
        assert len(req.query) == 500

    def test_valid_offset_zero(self):
        """Offset of 0 should be accepted."""
        req = SearchRequest(query="test", offset=0)
        assert req.offset == 0
