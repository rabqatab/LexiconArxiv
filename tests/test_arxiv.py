"""Tests for arXiv collector."""

import pytest
import respx
from httpx import Response

from src.collectors.arxiv import ArxivCollector, ARXIV_CATEGORIES
from src.models.paper import SourceType


# Sample arXiv API XML response
ARXIV_XML_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>10</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2304.12345v2</id>
    <updated>2023-04-20T00:00:00Z</updated>
    <published>2023-04-15T00:00:00Z</published>
    <title>KULLM: Korean Large Language Model</title>
    <summary>We present KULLM, a Korean instruction-tuned large language model.</summary>
    <author>
      <name>Seungjun Lee</name>
    </author>
    <author>
      <name>Jihyun Kim</name>
    </author>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
    <link href="http://arxiv.org/abs/2304.12345v2" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2304.12345v2" rel="related" type="application/pdf"/>
  </entry>
</feed>"""

ARXIV_EMPTY_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>10</opensearch:itemsPerPage>
</feed>"""


class TestArxivCollector:
    @pytest.fixture
    def collector(self):
        return ArxivCollector(email="test@example.com")

    def test_init(self, collector):
        assert collector.email == "test@example.com"
        assert collector.SOURCE_TYPE == SourceType.ARXIV
        assert collector.DEFAULT_TIMEOUT == 60.0

    def test_get_source_name(self, collector):
        assert collector.get_source_name() == "arXiv"

    def test_build_query_simple(self, collector):
        query = collector._build_query("language model", None)
        assert 'all:"language model"' in query

    def test_build_query_with_categories(self, collector):
        query = collector._build_query("test", ["cs.CL", "cs.AI"])
        assert "cat:cs.CL" in query
        assert "cat:cs.AI" in query

    def test_build_query_empty(self, collector):
        query = collector._build_query("", None)
        # Should default to AI/NLP categories
        assert "cat:cs.CL" in query

    def test_clean_arxiv_id(self, collector):
        assert collector._clean_arxiv_id("2304.12345") == "2304.12345"
        assert collector._clean_arxiv_id("http://arxiv.org/abs/2304.12345") == "2304.12345"
        assert collector._clean_arxiv_id("https://arxiv.org/abs/2304.12345") == "2304.12345"

    def test_extract_arxiv_id(self, collector):
        assert collector._extract_arxiv_id("http://arxiv.org/abs/2304.12345v2") == "2304.12345v2"

    @respx.mock
    @pytest.mark.asyncio
    async def test_search(self, collector):
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=ARXIV_XML_RESPONSE)
        )

        async with collector:
            papers = await collector.search("Korean LLM", limit=10)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "KULLM: Korean Large Language Model"
        assert paper.source == SourceType.ARXIV
        assert paper.arxiv_id == "2304.12345"
        assert paper.year == 2023
        assert len(paper.authors) == 2
        assert paper.venue == "arXiv"
        assert paper.venue_type == "preprint"

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_with_categories(self, collector):
        from urllib.parse import unquote

        route = respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=ARXIV_XML_RESPONSE)
        )

        async with collector:
            await collector.search("test", categories=["cs.CL"])

        request = route.calls[0].request
        url_decoded = unquote(str(request.url))
        assert "cat:cs.CL" in url_decoded

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_empty_results(self, collector):
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=ARXIV_EMPTY_RESPONSE)
        )

        async with collector:
            papers = await collector.search("nonexistent query xyz")

        assert len(papers) == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_id(self, collector):
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=ARXIV_XML_RESPONSE)
        )

        async with collector:
            paper = await collector.fetch_by_id("2304.12345")

        assert paper is not None
        assert paper.arxiv_id == "2304.12345"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_by_id_not_found(self, collector):
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=ARXIV_EMPTY_RESPONSE)
        )

        async with collector:
            paper = await collector.fetch_by_id("9999.99999")

        assert paper is None


class TestArxivParser:
    @pytest.fixture
    def collector(self):
        return ArxivCollector()

    @pytest.fixture
    def parsed_entry(self):
        """Create a mock feedparser entry with attribute access."""
        import feedparser

        # Parse actual XML to get proper feedparser entry
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2304.12345v2</id>
            <published>2023-04-15T00:00:00Z</published>
            <title>KULLM: Korean Large Language Model</title>
            <summary>We present KULLM, a Korean instruction-tuned model.</summary>
            <author><name>Seungjun Lee</name></author>
            <author><name>Jihyun Kim</name></author>
            <arxiv:primary_category term="cs.CL"/>
            <category term="cs.CL"/>
            <category term="cs.AI"/>
            <link href="http://arxiv.org/abs/2304.12345v2" rel="alternate" type="text/html"/>
            <link href="http://arxiv.org/pdf/2304.12345v2" rel="related" type="application/pdf"/>
          </entry>
        </feed>"""
        feed = feedparser.parse(xml)
        return feed.entries[0]

    def test_parse_entry(self, collector, parsed_entry):
        paper = collector._parse_entry(parsed_entry)

        assert paper is not None
        assert "KULLM" in paper.title
        assert paper.arxiv_id == "2304.12345"
        assert paper.year == 2023
        assert paper.month == 4
        assert len(paper.authors) == 2
        assert "cs.CL" in paper.categories

    def test_parse_entry_urls(self, collector, parsed_entry):
        paper = collector._parse_entry(parsed_entry)

        assert paper.abstract_url == "https://arxiv.org/abs/2304.12345"
        # PDF URL comes from the feed link or is constructed from base ID
        assert "arxiv.org/pdf/2304.12345" in paper.pdf_url


class TestArxivCategories:
    def test_categories_defined(self):
        assert "cs.CL" in ARXIV_CATEGORIES
        assert "cs.AI" in ARXIV_CATEGORIES
        assert "cs.LG" in ARXIV_CATEGORIES
        assert ARXIV_CATEGORIES["cs.CL"] == "Computation and Language"
