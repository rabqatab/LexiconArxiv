"""Tests for deduplication module (src/core/deduplication.py)."""

import pytest

from src.core.deduplication import (
    Deduplicator,
    DuplicateResult,
    SOURCE_PRIORITY,
    are_titles_similar,
)
from src.models.paper import RawPaper, SourceType, Author


class TestDeduplicator:
    """Tests for Deduplicator class."""

    @pytest.fixture
    def deduplicator(self):
        return Deduplicator()

    @pytest.fixture
    def sample_paper(self):
        """Create a sample paper for testing."""
        return RawPaper(
            source=SourceType.OPENALEX,
            source_id="W123456",
            title="Test Paper Title",
            year=2023,
            doi="10.1234/test.2023.001",
            openalex_id="W123456",
            authors=[Author(name="John Doe")],
        )

    @pytest.fixture
    def sample_acl_paper(self):
        """Create a sample ACL paper for testing."""
        return RawPaper(
            source=SourceType.ACL,
            source_id="2023.acl-long.1",
            title="ACL Paper Title",
            year=2023,
            doi="10.18653/v1/2023.acl-long.1",
            acl_id="2023.acl-long.1",
            authors=[Author(name="Jane Smith")],
        )

    def test_init(self, deduplicator):
        """Test deduplicator initialization."""
        stats = deduplicator.stats
        assert stats["dois"] == 0
        assert stats["openalex_ids"] == 0
        assert stats["acl_ids"] == 0
        assert stats["title_years"] == 0

    def test_normalize_title(self):
        """Test title normalization."""
        # Lowercase
        assert Deduplicator.normalize_title("HELLO WORLD") == "hello world"

        # Remove punctuation
        assert Deduplicator.normalize_title("Hello, World!") == "hello world"

        # Collapse whitespace
        assert Deduplicator.normalize_title("Hello   World") == "hello world"

        # Empty string
        assert Deduplicator.normalize_title("") == ""
        assert Deduplicator.normalize_title(None) == ""

    def test_make_title_year_key(self):
        """Test title-year key creation."""
        key = Deduplicator.make_title_year_key("Test Paper", 2023)
        assert key == "test paper|2023"

        # With None year
        key_no_year = Deduplicator.make_title_year_key("Test Paper", None)
        assert key_no_year == "test paper|unknown"

    def test_add_paper(self, deduplicator, sample_paper):
        """Test adding a paper to the deduplicator."""
        deduplicator.add_paper(sample_paper)

        stats = deduplicator.stats
        assert stats["dois"] == 1
        assert stats["openalex_ids"] == 1
        assert stats["title_years"] == 1

    def test_add_acl_paper(self, deduplicator, sample_acl_paper):
        """Test adding an ACL paper to the deduplicator."""
        deduplicator.add_paper(sample_acl_paper)

        stats = deduplicator.stats
        assert stats["dois"] == 1
        assert stats["acl_ids"] == 1
        assert stats["title_years"] == 1

    def test_check_duplicate_by_doi(self, deduplicator, sample_paper):
        """Test duplicate detection by DOI."""
        deduplicator.add_paper(sample_paper)

        # Same DOI should be detected
        duplicate_paper = RawPaper(
            source=SourceType.ACL,
            source_id="different_id",
            title="Different Title",
            year=2023,
            doi="10.1234/TEST.2023.001",  # Same DOI, different case
        )

        result = deduplicator.check_duplicate(duplicate_paper)
        assert result.is_duplicate is True
        assert result.match_type == "doi"
        assert result.confidence == 1.0
        assert result.matched_source == SourceType.OPENALEX

    def test_check_duplicate_by_openalex_id(self, deduplicator, sample_paper):
        """Test duplicate detection by OpenAlex ID."""
        deduplicator.add_paper(sample_paper)

        duplicate_paper = RawPaper(
            source=SourceType.DBLP,
            source_id="different_id",
            title="Different Title",
            year=2023,
            openalex_id="W123456",  # Same OpenAlex ID
        )

        result = deduplicator.check_duplicate(duplicate_paper)
        assert result.is_duplicate is True
        assert result.match_type == "openalex_id"
        assert result.matched_source == SourceType.OPENALEX

    def test_check_duplicate_by_acl_id(self, deduplicator, sample_acl_paper):
        """Test duplicate detection by ACL ID."""
        deduplicator.add_paper(sample_acl_paper)

        duplicate_paper = RawPaper(
            source=SourceType.DBLP,
            source_id="different_id",
            title="Different Title",
            year=2023,
            acl_id="2023.acl-long.1",  # Same ACL ID
        )

        result = deduplicator.check_duplicate(duplicate_paper)
        assert result.is_duplicate is True
        assert result.match_type == "acl_id"
        assert result.matched_source == SourceType.ACL

    def test_check_duplicate_by_title_year(self, deduplicator, sample_paper):
        """Test duplicate detection by title + year."""
        deduplicator.add_paper(sample_paper)

        duplicate_paper = RawPaper(
            source=SourceType.ACL,
            source_id="different_id",
            title="TEST PAPER TITLE",  # Same title, different case
            year=2023,
        )

        result = deduplicator.check_duplicate(duplicate_paper)
        assert result.is_duplicate is True
        assert result.match_type == "title_year"
        assert result.confidence == 0.95
        assert result.matched_source == SourceType.OPENALEX

    def test_check_not_duplicate(self, deduplicator, sample_paper):
        """Test non-duplicate detection."""
        deduplicator.add_paper(sample_paper)

        new_paper = RawPaper(
            source=SourceType.ACL,
            source_id="new_id",
            title="Completely Different Paper",
            year=2024,
            doi="10.5678/different.2024.001",
        )

        result = deduplicator.check_duplicate(new_paper)
        assert result.is_duplicate is False
        assert result.match_type is None

    def test_check_and_add(self, deduplicator, sample_paper):
        """Test combined check and add operation."""
        # First add should not be duplicate
        result1 = deduplicator.check_and_add(sample_paper)
        assert result1.is_duplicate is False
        assert deduplicator.stats["dois"] == 1

        # Second add with same DOI should be duplicate
        duplicate_paper = RawPaper(
            source=SourceType.ACL,
            source_id="different",
            title="Different",
            doi=sample_paper.doi,
        )
        result2 = deduplicator.check_and_add(duplicate_paper)
        assert result2.is_duplicate is True
        # Stats should not increase
        assert deduplicator.stats["dois"] == 1

    def test_clear(self, deduplicator, sample_paper):
        """Test clearing the deduplicator."""
        deduplicator.add_paper(sample_paper)
        assert deduplicator.stats["dois"] == 1

        deduplicator.clear()
        stats = deduplicator.stats
        assert stats["dois"] == 0
        assert stats["openalex_ids"] == 0
        assert stats["acl_ids"] == 0
        assert stats["title_years"] == 0


class TestSourcePriority:
    """Tests for source priority functionality."""

    def test_source_priority_defined(self):
        """Test that source priorities are defined."""
        assert SourceType.OPENALEX in SOURCE_PRIORITY
        assert SourceType.ACL in SOURCE_PRIORITY
        assert SourceType.DBLP in SOURCE_PRIORITY

    def test_openalex_highest_priority(self):
        """Test that OpenAlex has highest priority."""
        assert SOURCE_PRIORITY[SourceType.OPENALEX] < SOURCE_PRIORITY[SourceType.ACL]
        assert SOURCE_PRIORITY[SourceType.OPENALEX] < SOURCE_PRIORITY[SourceType.DBLP]

    def test_should_prefer_new(self):
        """Test source preference comparison."""
        deduplicator = Deduplicator()

        # OpenAlex should be preferred over ACL
        assert deduplicator.should_prefer_new(SourceType.ACL, SourceType.OPENALEX) is True

        # OpenAlex should be preferred over DBLP
        assert deduplicator.should_prefer_new(SourceType.DBLP, SourceType.OPENALEX) is True

        # ACL should be preferred over DBLP
        assert deduplicator.should_prefer_new(SourceType.DBLP, SourceType.ACL) is True

        # Should not prefer lower priority
        assert deduplicator.should_prefer_new(SourceType.OPENALEX, SourceType.DBLP) is False
        assert deduplicator.should_prefer_new(SourceType.ACL, SourceType.DBLP) is False


class TestTitleSimilarity:
    """Tests for title similarity functions."""

    def test_identical_titles(self):
        """Test exact title match."""
        assert are_titles_similar("Test Paper Title", "Test Paper Title") is True

    def test_normalized_match(self):
        """Test match after normalization."""
        assert are_titles_similar("Test Paper Title", "test paper title") is True
        assert are_titles_similar("Test Paper Title!", "Test Paper Title") is True

    def test_different_titles(self):
        """Test non-matching titles."""
        assert are_titles_similar("Test Paper Title", "Completely Different") is False

    def test_empty_titles(self):
        """Test with empty or None titles."""
        assert are_titles_similar("", "Test") is False
        assert are_titles_similar("Test", "") is False
        assert are_titles_similar("", "") is False

    def test_similar_titles(self):
        """Test partially matching titles."""
        # High overlap
        title1 = "Efficient Methods for Natural Language Processing"
        title2 = "Efficient Methods for Natural Language Understanding"
        # These share many words, should be similar at 0.9 threshold
        result = are_titles_similar(title1, title2, threshold=0.7)
        assert result is True

    def test_custom_threshold(self):
        """Test with custom threshold."""
        title1 = "Deep Learning for NLP"
        title2 = "Deep Learning Applications"

        # Should pass at lower threshold
        assert are_titles_similar(title1, title2, threshold=0.3) is True

        # Should fail at higher threshold
        assert are_titles_similar(title1, title2, threshold=0.9) is False


class TestCrossSourceDeduplication:
    """Tests for cross-source deduplication scenarios."""

    @pytest.fixture
    def deduplicator(self):
        return Deduplicator()

    def test_openalex_then_acl(self, deduplicator):
        """Test deduplication when OpenAlex paper is added first."""
        openalex_paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id="W123",
            title="Cross-Source Paper",
            year=2023,
            doi="10.1234/paper.2023",
        )
        deduplicator.add_paper(openalex_paper)

        acl_paper = RawPaper(
            source=SourceType.ACL,
            source_id="2023.acl-long.1",
            title="Cross-Source Paper",
            year=2023,
            doi="10.1234/paper.2023",
        )
        result = deduplicator.check_duplicate(acl_paper)

        assert result.is_duplicate is True
        assert result.matched_source == SourceType.OPENALEX

    def test_acl_then_openalex(self, deduplicator):
        """Test deduplication when ACL paper is added first."""
        acl_paper = RawPaper(
            source=SourceType.ACL,
            source_id="2023.acl-long.1",
            title="Cross-Source Paper",
            year=2023,
            doi="10.1234/paper.2023",
            acl_id="2023.acl-long.1",
        )
        deduplicator.add_paper(acl_paper)

        openalex_paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id="W123",
            title="Cross-Source Paper",
            year=2023,
            doi="10.1234/paper.2023",
        )
        result = deduplicator.check_duplicate(openalex_paper)

        assert result.is_duplicate is True
        assert result.matched_source == SourceType.ACL

        # Check if we should prefer the new OpenAlex source
        should_prefer = deduplicator.should_prefer_new(
            SourceType.ACL, SourceType.OPENALEX
        )
        assert should_prefer is True

    def test_multiple_sources_same_paper(self, deduplicator):
        """Test paper appearing in multiple sources."""
        # Add from DBLP first
        dblp_paper = RawPaper(
            source=SourceType.DBLP,
            source_id="conf/acl/Test23",
            title="Multi-Source Paper",
            year=2023,
            doi="10.18653/v1/2023.acl-long.100",
        )
        deduplicator.add_paper(dblp_paper)

        # Try to add from ACL
        acl_paper = RawPaper(
            source=SourceType.ACL,
            source_id="2023.acl-long.100",
            title="Multi-Source Paper",
            year=2023,
            doi="10.18653/v1/2023.acl-long.100",
        )
        result_acl = deduplicator.check_duplicate(acl_paper)
        assert result_acl.is_duplicate is True

        # Try to add from OpenAlex
        openalex_paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id="W456",
            title="Multi-Source Paper",
            year=2023,
            doi="10.18653/v1/2023.acl-long.100",
        )
        result_openalex = deduplicator.check_duplicate(openalex_paper)
        assert result_openalex.is_duplicate is True
