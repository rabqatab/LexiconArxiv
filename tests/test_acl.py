"""Tests for ACL Anthology collector."""

import pytest
import respx
from httpx import Response

from src.collectors.acl import ACLAnthologyCollector, ACL_VENUES
from src.models.paper import SourceType, PaperType


class TestACLAnthologyCollector:
    @pytest.fixture
    def collector(self):
        return ACLAnthologyCollector(email="test@example.com")

    def test_init(self, collector):
        assert collector.email == "test@example.com"
        assert collector.SOURCE_TYPE == SourceType.ACL

    def test_get_source_name(self, collector):
        assert collector.get_source_name() == "ACL Anthology"

    def test_acl_venue_ids(self, collector):
        assert "ACL" in collector.ACL_VENUE_IDS
        assert "EMNLP" in collector.ACL_VENUE_IDS
        assert "NAACL" in collector.ACL_VENUE_IDS

    @respx.mock
    @pytest.mark.asyncio
    async def test_search(self, collector, s2_search_response):
        respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
            return_value=Response(200, json=s2_search_response)
        )

        async with collector:
            papers = await collector.search("natural language", limit=10)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "Efficient Methods for Natural Language Understanding"
        assert paper.source == SourceType.ACL
        assert paper.year == 2023

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_filters_non_acl(self, collector):
        non_acl_response = {
            "total": 1,
            "offset": 0,
            "data": [
                {
                    "paperId": "xyz789",
                    "title": "Some Paper",
                    "year": 2023,
                    "venue": "ICML",  # Not an ACL venue
                    "authors": [{"name": "Author"}],
                }
            ],
        }
        respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
            return_value=Response(200, json=non_acl_response)
        )

        async with collector:
            papers = await collector.search("test", limit=10)

        # Non-ACL papers should be filtered out
        assert len(papers) == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, collector, s2_search_response):
        route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
            return_value=Response(200, json=s2_search_response)
        )

        async with collector:
            await collector.search("test", year_from=2022, year_to=2024)

        request = route.calls[0].request
        assert "year=2022-2024" in str(request.url)

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_id(self, collector, s2_paper_response):
        respx.get("https://api.semanticscholar.org/graph/v1/paper/ACL:2023.acl-long.100").mock(
            return_value=Response(200, json=s2_paper_response)
        )

        async with collector:
            paper = await collector.fetch_by_id("2023.acl-long.100")

        assert paper is not None
        assert paper.acl_id == "2023.acl-long.100"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_s2_id(self, collector, s2_paper_response):
        respx.get("https://api.semanticscholar.org/graph/v1/paper/abc123def456").mock(
            return_value=Response(200, json=s2_paper_response)
        )

        async with collector:
            paper = await collector.fetch_by_s2_id("abc123def456")

        assert paper is not None


class TestACLParser:
    @pytest.fixture
    def collector(self):
        return ACLAnthologyCollector()

    def test_is_acl_venue(self, collector):
        assert collector._is_acl_venue("ACL 2023", ["ACL"])
        assert collector._is_acl_venue("EMNLP 2023", ["EMNLP"])
        assert collector._is_acl_venue("Findings of ACL", ["ACL"])
        assert not collector._is_acl_venue("ICML", ["ACL", "EMNLP"])
        assert not collector._is_acl_venue("", ["ACL"])

    def test_map_venue_to_type(self, collector):
        assert collector._map_venue_to_type("ACL 2023") == "conference"
        assert collector._map_venue_to_type("SemEval Workshop") == "workshop"
        assert collector._map_venue_to_type("TACL") == "journal"
        assert collector._map_venue_to_type("Computational Linguistics") == "journal"

    def test_map_paper_type(self, collector):
        assert collector._map_paper_type(["Review"]) == PaperType.SURVEY
        assert collector._map_paper_type(["Dataset"]) == PaperType.DATASET
        assert collector._map_paper_type(["Conference"]) == PaperType.METHOD
        assert collector._map_paper_type([]) == PaperType.OTHER

    def test_parse_s2_paper(self, collector, s2_paper_response):
        paper = collector._parse_s2_paper(s2_paper_response)

        assert paper is not None
        assert paper.title == "Efficient Methods for Natural Language Understanding"
        assert paper.doi == "10.18653/v1/2023.acl-long.100"
        assert paper.arxiv_id == "2305.54321"
        assert paper.acl_id == "2023.acl-long.100"
        assert paper.citation_count == 25
        assert len(paper.authors) == 2

    def test_parse_s2_paper_urls(self, collector, s2_paper_response):
        paper = collector._parse_s2_paper(s2_paper_response)

        assert paper.pdf_url == "https://aclanthology.org/2023.acl-long.100.pdf"
        assert paper.abstract_url == "https://aclanthology.org/2023.acl-long.100"

    def test_parse_s2_paper_missing_title(self, collector):
        data = {"paperId": "abc123"}
        paper = collector._parse_s2_paper(data)
        assert paper is None


class TestACLVenues:
    def test_venues_defined(self):
        assert "P" in ACL_VENUES
        assert ACL_VENUES["P"] == "ACL"
        assert ACL_VENUES["D"] == "EMNLP"
        assert ACL_VENUES["N"] == "NAACL"
