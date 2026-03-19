"""Tests for async arXiv and OpenAlex on-demand search clients."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.core.search.arxiv_client import ArxivClient
from src.core.search.openalex_client import OpenAlexSearchClient

# ---------------------------------------------------------------------------
# arXiv fixtures
# ---------------------------------------------------------------------------

SAMPLE_ARXIV_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Test Paper About Transformers</title>
    <summary>This paper explores transformer architectures.</summary>
    <author><name>Author A</name></author>
    <author><name>Author B</name></author>
    <published>2023-01-01T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2301.00001v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>
"""

SAMPLE_OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "Test OpenAlex Paper",
            "doi": "https://doi.org/10.1234/test",
            "publication_year": 2023,
            "authorships": [{"author": {"display_name": "Author X"}}],
            "primary_location": {"source": {"display_name": "NeurIPS"}},
            "cited_by_count": 100,
            "abstract_inverted_index": {"This": [0], "is": [1], "a": [2], "test": [3]},
        }
    ]
}


# ---------------------------------------------------------------------------
# arXiv client tests
# ---------------------------------------------------------------------------


class TestArxivClient:
    @pytest.mark.asyncio
    async def test_search_returns_normalized_results(self):
        mock_response = httpx.Response(
            200, text=SAMPLE_ARXIV_ATOM,
            request=httpx.Request("GET", "http://export.arxiv.org/api/query"),
        )

        async with ArxivClient() as client:
            client._client.get = AsyncMock(return_value=mock_response)
            results = await client.search("transformers")

        assert len(results) == 1
        paper = results[0]
        assert paper["title"] == "Test Paper About Transformers"
        assert paper["abstract"] == "This paper explores transformer architectures."
        assert paper["authors"] == ["Author A", "Author B"]
        assert paper["arxiv_id"] == "2301.00001"
        assert paper["year"] == 2023
        assert paper["doi"] is None
        assert paper["venue"] is None
        assert paper["url"] == "http://arxiv.org/abs/2301.00001v1"
        assert paper["pdf_url"] == "http://arxiv.org/pdf/2301.00001v1"
        assert paper["source"] == "arxiv"

    @pytest.mark.asyncio
    async def test_search_handles_error_gracefully(self):
        async with ArxivClient() as client:
            client._client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
                "Server error", request=httpx.Request("GET", "http://test"), response=httpx.Response(500)
            ))
            results = await client.search("transformers")

        assert results == []

    @pytest.mark.asyncio
    async def test_parse_feed_handles_malformed_xml(self):
        client = ArxivClient()
        assert client._parse_feed("not valid xml <<>") == []

    @pytest.mark.asyncio
    async def test_search_without_context_manager_raises(self):
        client = ArxivClient()
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.search("test")


# ---------------------------------------------------------------------------
# OpenAlex client tests
# ---------------------------------------------------------------------------


class TestOpenAlexSearchClient:
    @pytest.mark.asyncio
    async def test_search_returns_normalized_results(self):
        mock_response = httpx.Response(
            200, json=SAMPLE_OPENALEX_JSON,
            request=httpx.Request("GET", "https://api.openalex.org/works"),
        )

        with patch("src.core.search.openalex_client.get_openalex_api_keys", return_value=[]), \
             patch("src.core.search.openalex_client.get_openalex_email", return_value="test@example.com"):
            async with OpenAlexSearchClient() as client:
                client._client.get = AsyncMock(return_value=mock_response)
                results = await client.search("test paper")

        assert len(results) == 1
        paper = results[0]
        assert paper["title"] == "Test OpenAlex Paper"
        assert paper["abstract"] == "This is a test"
        assert paper["authors"] == ["Author X"]
        assert paper["doi"] == "10.1234/test"
        assert paper["year"] == 2023
        assert paper["venue"] == "NeurIPS"
        assert paper["arxiv_id"] is None
        assert paper["url"] == "https://openalex.org/W123"
        assert paper["pdf_url"] is None
        assert paper["source"] == "openalex"

    @pytest.mark.asyncio
    async def test_search_handles_error_gracefully(self):
        with patch("src.core.search.openalex_client.get_openalex_api_keys", return_value=[]), \
             patch("src.core.search.openalex_client.get_openalex_email", return_value=None):
            async with OpenAlexSearchClient() as client:
                client._client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
                    "Server error", request=httpx.Request("GET", "http://test"), response=httpx.Response(500)
                ))
                results = await client.search("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_without_context_manager_raises(self):
        client = OpenAlexSearchClient()
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.search("test")

    @pytest.mark.asyncio
    async def test_reconstruct_abstract_none(self):
        client = OpenAlexSearchClient()
        assert client._reconstruct_abstract(None) is None

    @pytest.mark.asyncio
    async def test_reconstruct_abstract_empty(self):
        client = OpenAlexSearchClient()
        assert client._reconstruct_abstract({}) is None

    @pytest.mark.asyncio
    async def test_normalize_work_strips_doi_prefix(self):
        client = OpenAlexSearchClient()
        work = {
            "id": "https://openalex.org/W999",
            "title": "DOI Test",
            "doi": "https://doi.org/10.5555/example",
            "publication_year": 2024,
            "authorships": [],
            "primary_location": None,
            "abstract_inverted_index": None,
        }
        result = client._normalize_work(work)
        assert result["doi"] == "10.5555/example"
        assert result["abstract"] is None

    @pytest.mark.asyncio
    async def test_search_uses_api_key_when_available(self):
        mock_response = httpx.Response(
            200, json={"results": []},
            request=httpx.Request("GET", "https://api.openalex.org/works"),
        )

        with patch("src.core.search.openalex_client.get_openalex_api_keys", return_value=["my-key"]), \
             patch("src.core.search.openalex_client.get_openalex_email", return_value=None):
            async with OpenAlexSearchClient() as client:
                client._client.get = AsyncMock(return_value=mock_response)
                await client.search("test")

                # Verify api_key was passed in params
                call_kwargs = client._client.get.call_args
                params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
                assert params["api_key"] == "my-key"
                assert "mailto" not in params
