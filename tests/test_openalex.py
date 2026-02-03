"""Tests for OpenAlex collector."""

import pytest
import respx
from httpx import Response

from src.collectors.openalex import OpenAlexCollector, CONCEPT_IDS
from src.models.paper import SourceType


class TestOpenAlexCollector:
    @pytest.fixture
    def collector(self):
        return OpenAlexCollector(email="test@example.com")

    def test_init(self, collector):
        assert collector.email == "test@example.com"
        assert collector.SOURCE_TYPE == SourceType.OPENALEX

    def test_get_source_name(self, collector):
        assert collector.get_source_name() == "OpenAlex"

    @respx.mock
    @pytest.mark.asyncio
    async def test_search(self, collector, openalex_search_response):
        respx.get("https://api.openalex.org/works").mock(
            return_value=Response(200, json=openalex_search_response)
        )

        async with collector:
            papers = await collector.search("Korean LLM", limit=10)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "KULLM: Korean Large Language Model"
        assert paper.source == SourceType.OPENALEX
        assert paper.year == 2023
        assert len(paper.authors) == 2
        assert paper.authors[0].name == "Seungjun Lee"
        assert paper.authors[0].affiliation == "KAIST"

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, collector, openalex_search_response):
        from urllib.parse import unquote

        route = respx.get("https://api.openalex.org/works").mock(
            return_value=Response(200, json=openalex_search_response)
        )

        async with collector:
            await collector.search("test", year_from=2022, year_to=2024)

        # Check that filter was included in request (URL is encoded)
        request = route.calls[0].request
        url_decoded = unquote(str(request.url))
        assert "from_publication_date:2022-01-01" in url_decoded
        assert "to_publication_date:2024-12-31" in url_decoded

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_ai_nlp(self, collector, openalex_search_response):
        route = respx.get("https://api.openalex.org/works").mock(
            return_value=Response(200, json=openalex_search_response)
        )

        async with collector:
            await collector.search_ai_nlp("test")

        # Check that concept filters were included
        request = route.calls[0].request
        assert CONCEPT_IDS["artificial_intelligence"] in str(request.url)

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_id(self, collector, openalex_work_response):
        respx.get("https://api.openalex.org/works/W2741809807").mock(
            return_value=Response(200, json=openalex_work_response)
        )

        async with collector:
            paper = await collector.fetch_by_id("W2741809807")

        assert paper is not None
        assert paper.title == "KULLM: Korean Large Language Model"
        assert paper.openalex_id == "W2741809807"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_doi(self, collector, openalex_work_response):
        respx.get("https://api.openalex.org/works/https://doi.org/10.1234/test").mock(
            return_value=Response(200, json=openalex_work_response)
        )

        async with collector:
            paper = await collector.fetch_by_doi("10.1234/test")

        assert paper is not None

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_id_not_found(self, collector):
        respx.get("https://api.openalex.org/works/W9999999999").mock(
            return_value=Response(404, json={"error": "not found"})
        )

        async with collector:
            paper = await collector.fetch_by_id("W9999999999")

        assert paper is None


class TestOpenAlexParser:
    @pytest.fixture
    def collector(self):
        return OpenAlexCollector()

    def test_reconstruct_abstract(self, collector):
        inverted_index = {
            "We": [0],
            "present": [1],
            "a": [2],
            "method.": [3],
        }
        abstract = collector._reconstruct_abstract(inverted_index)
        assert abstract == "We present a method."

    def test_reconstruct_abstract_empty(self, collector):
        assert collector._reconstruct_abstract(None) is None
        assert collector._reconstruct_abstract({}) is None

    def test_map_paper_type(self, collector):
        from src.models.paper import PaperType

        assert collector._map_paper_type("article") == PaperType.METHOD
        assert collector._map_paper_type("review") == PaperType.SURVEY
        assert collector._map_paper_type("dataset") == PaperType.DATASET
        assert collector._map_paper_type("unknown") == PaperType.OTHER

    def test_parse_work(self, collector, openalex_work_response):
        paper = collector._parse_work(openalex_work_response)

        assert paper is not None
        assert paper.title == "KULLM: Korean Large Language Model"
        assert paper.doi == "10.18653/v1/2023.acl-long.1"
        assert paper.citation_count == 42
        assert paper.venue == "ACL 2023"
        assert "Natural Language Processing" in paper.categories

    def test_parse_work_missing_title(self, collector):
        work = {"id": "W123"}
        paper = collector._parse_work(work)
        assert paper is None
