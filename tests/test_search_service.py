"""Tests for the SearchService."""

import pytest
import respx
from httpx import Response
from qdrant_client import QdrantClient, models

from src.core.constants import ALL_DENSE_VECTORS
from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage


class TestSearchService:
    """Test hybrid search orchestration."""

    def setup_method(self):
        self.collection = "_test_search_service"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        # Mirror the production 9-dense-vector schema so RetrievalConfig defaults
        # (multi_vector over structured-abstract + section-method + section-task)
        # don't 400 on the test collection. Building from ALL_DENSE_VECTORS keeps
        # the fixture in sync with production even when new vectors are added.
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                name: models.VectorParams(size=4, distance=models.Distance.COSINE)
                for name in ALL_DENSE_VECTORS
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        # Fan a single canonical embedding across all dense vector names so the
        # search's multi-vector prefetch (structured-abstract + section-method +
        # section-task by default) can retrieve either point. Mirrors reality:
        # all dense vectors of a real paper come from the same abstract text.
        def _vector_bundle(dense_vec: list[float], bm25_text: str) -> dict:
            bundle: dict = {name: dense_vec for name in ALL_DENSE_VECTORS}
            bundle["bm25"] = models.Document(text=bm25_text, model="qdrant/bm25")
            return bundle

        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000001",
                    vector=_vector_bundle(
                        [0.9, 0.1, 0.1, 0.1],
                        "retrieval augmented generation for knowledge tasks",
                    ),
                    payload={
                        "title": "RAG Paper", "abstract": "About retrieval augmented generation",
                        "authors": ["Author A"], "venue": "NeurIPS 2020", "year": 2020,
                        "tier": 0, "doi": "10.1234/rag", "citation_count": 3000,
                        "keywords": ["RAG", "retrieval"], "is_stub": False, "is_core": True,
                    },
                ),
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000002",
                    vector=_vector_bundle(
                        [0.1, 0.9, 0.1, 0.1],
                        "attention is all you need transformer architecture",
                    ),
                    payload={
                        "title": "Transformer Paper", "abstract": "About attention and transformers",
                        "authors": ["Author B"], "venue": "NeurIPS 2017", "year": 2017,
                        "tier": 0, "doi": "10.1234/transformer", "citation_count": 50000,
                        "keywords": ["attention", "transformer"], "is_stub": False, "is_core": True,
                    },
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_hybrid_search(self):
        async with respx.mock(assert_all_mocked=False) as respx_mock:
            fake_embedding = [0.85, 0.15, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(200, json={"embeddings": [fake_embedding]}),
            )
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            service = SearchService(storage=storage, target_dim=4)
            async with service:
                results = await service.search(query="retrieval augmented generation")
            assert results["search_mode"] == "hybrid"
            assert len(results["results"]) == 2
            assert results["results"][0]["title"] == "RAG Paper"

    @pytest.mark.asyncio
    async def test_bm25_fallback_when_ollama_down(self):
        async with respx.mock(assert_all_mocked=False) as respx_mock:
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(500, text="Server Error"),
            )
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            service = SearchService(storage=storage, target_dim=4, max_retries=1)
            async with service:
                results = await service.search(query="retrieval augmented generation")
            assert results["search_mode"] == "bm25_only"
            assert len(results["results"]) > 0

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self):
        async with respx.mock(assert_all_mocked=False) as respx_mock:
            fake_embedding = [0.5, 0.5, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0]
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(200, json={"embeddings": [fake_embedding]}),
            )
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            service = SearchService(storage=storage, target_dim=4)
            async with service:
                results = await service.search(query="neural network", year_min=2019)
            assert len(results["results"]) == 1
            assert results["results"][0]["year"] == 2020

    @pytest.mark.asyncio
    async def test_get_paper(self):
        storage = QdrantStorage(collection_name=self.collection)
        service = SearchService(storage=storage, target_dim=4)
        async with service:
            paper = await service.get_paper("aaaa0001-0000-0000-0000-000000000001")
        assert paper is not None
        assert paper["title"] == "RAG Paper"
        assert paper["is_core"] is True

    @pytest.mark.asyncio
    async def test_get_paper_not_found(self):
        storage = QdrantStorage(collection_name=self.collection)
        service = SearchService(storage=storage, target_dim=4)
        async with service:
            paper = await service.get_paper("nonexistent-id-0000-0000-000000000000")
        assert paper is None
