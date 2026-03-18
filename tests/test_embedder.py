import pytest
import respx
from httpx import Response
from qdrant_client import QdrantClient, models

from src.core.embedding.embedder import PaperEmbedder


class TestPaperEmbedder:
    """Test embedding generation via Ollama."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_single_abstract(self):
        fake_embedding = list(range(4096))
        route = respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": [fake_embedding]}),
        )
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract about ML"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 1024
        assert vectors[0] == list(range(1024))
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_batch(self):
        fake_embeddings = [list(range(4096)) for _ in range(3)]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": fake_embeddings}),
        )
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Abstract one", "Abstract two", "Abstract three"])
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_failure(self):
        fake_embedding = list(range(4096))
        route = respx.post("http://localhost:11434/api/embed")
        route.side_effect = [
            Response(500, text="Server Error"),
            Response(200, json={"embeddings": [fake_embedding]}),
        ]
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
            max_retries=3,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract"])
        assert len(vectors) == 1
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_after_max_retries(self):
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(500, text="Server Error"),
        )
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
            max_retries=2,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract"])
        assert vectors is None


class TestEmbedAndUpsert:
    """Test the combined embed + update_vectors pipeline."""

    def setup_method(self):
        self.collection = "_test_embed_upsert"
        self.qdrant = QdrantClient(url="http://localhost:6333")
        try:
            self.qdrant.delete_collection(self.collection)
        except Exception:
            pass
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(size=4, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        # Pre-insert payload-only points
        self.qdrant.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 1", "abstract": "Machine learning paper"},
                ),
                models.PointStruct(
                    id="aaaa0002-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 2", "abstract": "Natural language processing"},
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.qdrant.delete_collection(self.collection)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_embeds_and_updates_vectors(self):
        from src.core.storage.base import QdrantStorage

        # Mock only the Ollama embed call; Qdrant uses a real connection
        async with respx.mock(assert_all_mocked=False) as respx_mock:
            # Mock Ollama returning 8d vectors (will be truncated to 4 by target_dim)
            fake_embeddings = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                               [0.5, 0.6, 0.7, 0.8, 0.1, 0.2, 0.3, 0.4]]
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(200, json={"embeddings": fake_embeddings}),
            )
            # Allow all Qdrant traffic to pass through to real server
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            embedder = PaperEmbedder(
                ollama_base_url="http://localhost:11434",
                target_dim=4,  # Match test collection — truncated from 8d mock
            )

            papers = [
                ("aaaa0001-0000-0000-0000-000000000000", {"abstract": "Machine learning paper"}),
                ("aaaa0002-0000-0000-0000-000000000000", {"abstract": "Natural language processing"}),
            ]

            async with embedder:
                count = await embedder.embed_and_upsert_batch(
                    papers=papers,
                    storage=storage,
                    dense_vector_name="abstract-qwen3-8b",
                )

        assert count == 2

        # Verify vectors were stored (via update_vectors, not upsert)
        point = self.qdrant.retrieve(
            collection_name=self.collection,
            ids=["aaaa0001-0000-0000-0000-000000000000"],
            with_vectors=True,
            with_payload=True,
        )[0]
        assert "abstract-qwen3-8b" in point.vector
        assert len(point.vector["abstract-qwen3-8b"]) == 4  # Truncated from 8d mock
        # CRITICAL: Verify payloads were preserved (not wiped)
        assert point.payload["title"] == "Paper 1"
