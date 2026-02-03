"""Tests for DBLP crawler (src/core/dblp.py)."""

import pytest

from src.core.dblp import (
    DBLPCollector,
    DBLP_VENUES,
    get_dblp_venues,
    get_dblp_venue_info,
)
from src.models.paper import SourceType, PaperType, Author


class TestDBLPVenueConfig:
    """Tests for DBLP venue configuration."""

    def test_dblp_venues_defined(self):
        """Test that all expected DBLP venues are defined."""
        expected = ["recsys", "ecir", "icail", "jurix", "cikm", "wsdm"]
        for venue in expected:
            assert venue in DBLP_VENUES, f"Missing venue: {venue}"

    def test_get_dblp_venues(self):
        """Test get_dblp_venues returns list of venue names."""
        venues = get_dblp_venues()
        assert isinstance(venues, list)
        assert "recsys" in venues
        assert "icail" in venues

    def test_get_dblp_venue_info(self):
        """Test get_dblp_venue_info returns venue details."""
        info = get_dblp_venue_info("icail")
        assert info is not None
        assert "full_name" in info
        assert "tier" in info
        assert info["tier"] == 2  # Legal AI venue

    def test_get_dblp_venue_info_unknown(self):
        """Test get_dblp_venue_info returns None for unknown venue."""
        info = get_dblp_venue_info("unknown_venue")
        assert info is None

    def test_venue_tiers(self):
        """Test that venue tiers are correctly assigned."""
        # Tier 1 venues (IR)
        assert DBLP_VENUES["recsys"]["tier"] == 1
        assert DBLP_VENUES["ecir"]["tier"] == 1

        # Tier 2 venues (Legal AI)
        assert DBLP_VENUES["icail"]["tier"] == 2
        assert DBLP_VENUES["jurix"]["tier"] == 2

    def test_venue_queries(self):
        """Test that venue queries are correctly formatted."""
        for venue, info in DBLP_VENUES.items():
            assert "query" in info
            assert info["query"].startswith("venue:")


class TestDBLPCollector:
    """Tests for DBLPCollector class."""

    @pytest.fixture
    def sample_dblp_hit(self):
        """Sample DBLP API hit."""
        return {
            "@id": "123456",
            "info": {
                "key": "conf/recsys/DoeSmith23",
                "title": "Efficient Recommendation Methods",
                "authors": {
                    "author": [
                        {"text": "John Doe", "@pid": "d/JohnDoe"},
                        {"text": "Jane Smith 0001", "@pid": "s/JaneSmith0001"},
                    ]
                },
                "year": "2023",
                "venue": "RecSys",
                "doi": "10.1145/3604915.3608890",
                "ee": "https://doi.org/10.1145/3604915.3608890",
                "url": "https://dblp.org/rec/conf/recsys/DoeSmith23",
                "type": "Conference and Workshop Papers",
            },
        }

    @pytest.fixture
    def sample_dblp_hit_single_author(self):
        """Sample DBLP API hit with single author."""
        return {
            "@id": "654321",
            "info": {
                "key": "conf/icail/Author23",
                "title": "Legal AI Survey",
                "authors": {
                    "author": {"text": "Solo Author", "@pid": "a/SoloAuthor"},
                },
                "year": "2023",
                "venue": "ICAIL",
                "type": "Conference and Workshop Papers",
            },
        }

    def test_parse_hit(self, sample_dblp_hit):
        """Test parsing DBLP hit into RawPaper."""
        collector = DBLPCollector()
        venue_info = DBLP_VENUES["recsys"]

        paper = collector._parse_hit(sample_dblp_hit, "recsys", venue_info)

        assert paper is not None
        assert paper.title == "Efficient Recommendation Methods"
        assert paper.source == SourceType.DBLP
        assert paper.year == 2023
        assert paper.doi == "10.1145/3604915.3608890"
        assert paper.venue == "RecSys"
        assert paper.tier == 1
        assert paper.is_core is True

        # Check authors
        assert len(paper.authors) == 2
        assert paper.authors[0].name == "John Doe"
        # Author suffix should be stripped
        assert paper.authors[1].name == "Jane Smith"

    def test_parse_hit_single_author(self, sample_dblp_hit_single_author):
        """Test parsing DBLP hit with single author (dict, not list)."""
        collector = DBLPCollector()
        venue_info = DBLP_VENUES["icail"]

        paper = collector._parse_hit(sample_dblp_hit_single_author, "icail", venue_info)

        assert paper is not None
        assert len(paper.authors) == 1
        assert paper.authors[0].name == "Solo Author"

    def test_parse_authors_list(self):
        """Test author parsing with list of authors."""
        collector = DBLPCollector()

        authors_data = {
            "author": [
                {"text": "Author One", "@pid": "a/One"},
                {"text": "Author Two", "@pid": "a/Two"},
            ]
        }

        authors = collector._parse_authors(authors_data)

        assert len(authors) == 2
        assert authors[0].name == "Author One"
        assert authors[1].name == "Author Two"

    def test_parse_authors_single(self):
        """Test author parsing with single author as dict."""
        collector = DBLPCollector()

        authors_data = {
            "author": {"text": "Single Author", "@pid": "s/Single"},
        }

        authors = collector._parse_authors(authors_data)

        assert len(authors) == 1
        assert authors[0].name == "Single Author"

    def test_parse_authors_empty(self):
        """Test author parsing with empty or None data."""
        collector = DBLPCollector()

        assert collector._parse_authors(None) == []
        assert collector._parse_authors({}) == []
        assert collector._parse_authors({"author": []}) == []

    def test_parse_authors_string_names(self):
        """Test author parsing when author names are strings."""
        collector = DBLPCollector()

        authors_data = {
            "author": ["John Doe", "Jane Smith"]
        }

        authors = collector._parse_authors(authors_data)

        assert len(authors) == 2
        assert authors[0].name == "John Doe"
        assert authors[1].name == "Jane Smith"

    def test_determine_paper_type(self, sample_dblp_hit):
        """Test paper type determination."""
        collector = DBLPCollector()

        # Regular method paper
        assert collector._determine_paper_type(sample_dblp_hit) == PaperType.METHOD

        # Survey paper
        survey_hit = {"info": {"title": "A Survey of Recommendation Systems"}}
        assert collector._determine_paper_type(survey_hit) == PaperType.SURVEY

        # Dataset paper
        dataset_hit = {"info": {"title": "MovieLens Dataset 2023"}}
        assert collector._determine_paper_type(dataset_hit) == PaperType.DATASET

        # Demo paper
        demo_hit = {"info": {"title": "System Demonstration: RecBot"}}
        assert collector._determine_paper_type(demo_hit) == PaperType.DEMO

    def test_parse_hit_missing_title(self):
        """Test that hit without title returns None."""
        collector = DBLPCollector()
        venue_info = DBLP_VENUES["recsys"]

        hit = {"info": {"year": "2023", "venue": "RecSys"}}

        paper = collector._parse_hit(hit, "recsys", venue_info)
        assert paper is None

    def test_parse_hit_multiple_urls(self):
        """Test parsing hit with multiple electronic editions."""
        collector = DBLPCollector()
        venue_info = DBLP_VENUES["recsys"]

        hit = {
            "info": {
                "key": "conf/recsys/Test23",
                "title": "Test Paper",
                "year": "2023",
                "ee": [
                    "https://doi.org/10.1145/123456",
                    "https://arxiv.org/abs/2301.12345",
                ],
            }
        }

        paper = collector._parse_hit(hit, "recsys", venue_info)
        assert paper is not None
        # Should take first URL
        assert paper.pdf_url == "https://doi.org/10.1145/123456"

    def test_context_manager_error(self):
        """Test that accessing client without context manager raises error."""
        collector = DBLPCollector()

        with pytest.raises(RuntimeError, match="async context manager"):
            _ = collector.client


class TestDBLPAbstracts:
    """Tests for DBLP abstract handling."""

    def test_no_abstract_in_dblp(self):
        """Test that DBLP papers have no abstract (DBLP doesn't provide them)."""
        collector = DBLPCollector()
        venue_info = DBLP_VENUES["recsys"]

        hit = {
            "info": {
                "key": "conf/recsys/Test23",
                "title": "Test Paper",
                "year": "2023",
            }
        }

        paper = collector._parse_hit(hit, "recsys", venue_info)
        assert paper is not None
        assert paper.abstract is None
