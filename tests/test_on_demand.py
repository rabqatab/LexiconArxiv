"""Tests for async arXiv and OpenAlex on-demand search clients and orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core.search.arxiv_client import ArxivClient
from src.core.search.on_demand import OnDemandSearch
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


# ---------------------------------------------------------------------------
# On-demand orchestrator fixtures
# ---------------------------------------------------------------------------

ARXIV_PAPER_A = {
    "title": "Arxiv Paper A",
    "abstract": "About transformers",
    "authors": ["Author A"],
    "arxiv_id": "2301.00001",
    "doi": None,
    "year": 2023,
    "venue": None,
    "url": "http://arxiv.org/abs/2301.00001v1",
    "pdf_url": "http://arxiv.org/pdf/2301.00001v1",
    "source": "arxiv",
}

ARXIV_PAPER_B = {
    "title": "Arxiv Paper B",
    "abstract": "About attention mechanisms",
    "authors": ["Author B"],
    "arxiv_id": "2301.00002",
    "doi": "10.1234/shared",
    "year": 2023,
    "venue": None,
    "url": "http://arxiv.org/abs/2301.00002v1",
    "pdf_url": None,
    "source": "arxiv",
}

OPENALEX_PAPER_C = {
    "title": "OpenAlex Paper C",
    "abstract": "About language models",
    "authors": ["Author C"],
    "arxiv_id": None,
    "doi": "10.1234/openalex-c",
    "year": 2022,
    "venue": "NeurIPS",
    "url": "https://openalex.org/W100",
    "pdf_url": None,
    "source": "openalex",
}

OPENALEX_PAPER_DUP = {
    "title": "Duplicate of B via DOI",
    "abstract": "Same paper different source",
    "authors": ["Author B"],
    "arxiv_id": None,
    "doi": "10.1234/shared",
    "year": 2023,
    "venue": "ICML",
    "url": "https://openalex.org/W200",
    "pdf_url": None,
    "source": "openalex",
}


def _make_mock_storage():
    """Create a mock QdrantStorage with queries and stubs sub-objects."""
    storage = MagicMock()
    storage.queries.get_paper_by_doi.return_value = None
    storage.queries.get_paper_by_arxiv_id.return_value = None
    storage.stubs.get_stub_by_identifier.return_value = None
    storage.collection_name = "test_collection"
    return storage


# ---------------------------------------------------------------------------
# On-demand orchestrator tests
# ---------------------------------------------------------------------------


class TestOnDemandSearch:
    @pytest.mark.asyncio
    async def test_expand_returns_combined_results(self):
        """Both sources return results — verify combined, labeled, and stats."""
        storage = _make_mock_storage()
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[ARXIV_PAPER_A.copy()])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_C.copy()])

        result = await ods.expand("transformers", sources="both", limit=20)

        assert result["cached"] is False
        assert len(result["expanded_results"]) == 2
        assert result["expansion_stats"]["arxiv_fetched"] == 1
        assert result["expansion_stats"]["openalex_fetched"] == 1
        assert result["expansion_stats"]["deduplicated"] == 0
        # Both should be labeled external (nothing in corpus/stubs)
        for paper in result["expanded_results"]:
            assert paper["connection"] == "external"
            assert paper["connected_papers"] == []

    @pytest.mark.asyncio
    async def test_dedup_removes_duplicates_by_doi(self):
        """Same DOI from both sources should produce only one result."""
        storage = _make_mock_storage()
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[ARXIV_PAPER_B.copy()])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_DUP.copy()])

        result = await ods.expand("attention", sources="both", limit=20)

        # The duplicate should be removed — only one paper with doi 10.1234/shared
        dois = [p.get("doi") for p in result["expanded_results"] if p.get("doi") == "10.1234/shared"]
        assert len(dois) == 1
        assert result["expansion_stats"]["deduplicated"] == 1

    @pytest.mark.asyncio
    async def test_caching_returns_cached_result(self):
        """Second call with same params should return cached result instantly."""
        storage = _make_mock_storage()
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[ARXIV_PAPER_A.copy()])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[])

        # First call — populates cache
        result1 = await ods.expand("transformers", sources="both", limit=20)
        assert result1["cached"] is False

        # Second call — should hit cache
        result2 = await ods.expand("transformers", sources="both", limit=20)
        assert result2["cached"] is True
        assert result2["query_time_ms"] == 0

        # arXiv should only have been called once
        assert ods._arxiv.search.await_count == 1

    @pytest.mark.asyncio
    async def test_expand_arxiv_only(self):
        """sources='arxiv' should not query OpenAlex at all."""
        storage = _make_mock_storage()
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[ARXIV_PAPER_A.copy()])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_C.copy()])

        result = await ods.expand("transformers", sources="arxiv", limit=20)

        assert result["expansion_stats"]["arxiv_fetched"] == 1
        assert result["expansion_stats"]["openalex_fetched"] == 0
        ods._openalex.search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_core_corpus_paper_counted_as_dedup(self):
        """A paper already in the core corpus should be flagged and counted as deduplicated."""
        storage = _make_mock_storage()
        storage.queries.get_paper_by_doi.side_effect = (
            lambda doi: {"title": "Existing"} if doi == "10.1234/openalex-c" else None
        )
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_C.copy()])

        result = await ods.expand("language models", sources="both", limit=20)

        assert result["expansion_stats"]["deduplicated"] == 1
        core_papers = [p for p in result["expanded_results"] if p["connection"] == "core"]
        assert len(core_papers) == 1

    @pytest.mark.asyncio
    async def test_connected_paper_labeled_correctly(self):
        """A paper that has a stub with cited_by should be labeled as connected."""
        storage = _make_mock_storage()
        storage.stubs.get_stub_by_identifier.side_effect = lambda ident: (
            ("stub-id-1", {"cited_by": ["core-paper-1"]})
            if ident == "doi:10.1234/openalex-c"
            else None
        )
        # Mock the client.retrieve call for resolving citing paper title
        mock_point = MagicMock()
        mock_point.payload = {"title": "Core Paper Title"}
        storage.client.retrieve.return_value = [mock_point]

        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(return_value=[])
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_C.copy()])

        result = await ods.expand("language models", sources="both", limit=20)

        connected = [p for p in result["expanded_results"] if p["connection"] == "connected"]
        assert len(connected) == 1
        assert connected[0]["connected_papers"][0]["title"] == "Core Paper Title"
        assert connected[0]["connected_papers"][0]["relation"] == "cited_by"
        assert result["expansion_stats"]["connected"] == 1

    @pytest.mark.asyncio
    async def test_expand_handles_source_error_gracefully(self):
        """If one source raises an exception, the other results still return."""
        storage = _make_mock_storage()
        ods = OnDemandSearch(storage=storage)
        ods._arxiv = MagicMock()
        ods._arxiv.search = AsyncMock(side_effect=RuntimeError("arXiv is down"))
        ods._openalex = MagicMock()
        ods._openalex.search = AsyncMock(return_value=[OPENALEX_PAPER_C.copy()])

        result = await ods.expand("test", sources="both", limit=20)

        assert result["expansion_stats"]["arxiv_fetched"] == 0
        assert result["expansion_stats"]["openalex_fetched"] == 1
        assert len(result["expanded_results"]) == 1

    @pytest.mark.asyncio
    async def test_cache_key_is_case_insensitive(self):
        """Cache keys should normalize query case."""
        ods = OnDemandSearch(storage=_make_mock_storage())
        key1 = ods._cache_key("Transformers", "both", 20)
        key2 = ods._cache_key("transformers", "both", 20)
        key3 = ods._cache_key("TRANSFORMERS", "both", 20)
        assert key1 == key2 == key3

    @pytest.mark.asyncio
    async def test_cache_key_differs_by_source(self):
        """Different source params should produce different cache keys."""
        ods = OnDemandSearch(storage=_make_mock_storage())
        key_both = ods._cache_key("test", "both", 20)
        key_arxiv = ods._cache_key("test", "arxiv", 20)
        assert key_both != key_arxiv
