import pytest
import respx
from httpx import Response
from qdrant_client import QdrantClient, models

from src.core.embedding.embedder import PaperEmbedder
from src.core.constants import (
    ALL_DENSE_VECTORS,
    EMBEDDING_VECTOR_NAME,
    STRUCTURED_VECTOR_NAME,
    SECTION_ROLES,
    SECTION_VECTOR_PREFIX,
)


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
        # Create collection with ALL dense vector configs
        vectors_config = {
            name: models.VectorParams(size=4, distance=models.Distance.COSINE)
            for name in ALL_DENSE_VECTORS
        }
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config=vectors_config,
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
                    payload={
                        "title": "Paper 1",
                        "abstract": "Machine learning paper",
                    },
                ),
                models.PointStruct(
                    id="aaaa0002-0000-0000-0000-000000000000",
                    vector={},
                    payload={
                        "title": "Paper 2",
                        "abstract": "Natural language processing",
                        "abstract_structure": {
                            "task": ["Classify text documents."],
                            "method": ["We use transformers for classification."],
                            "result": ["Our model achieves 95% accuracy."],
                        },
                    },
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

        # Paper 1: no structure -> 2 texts (abstract + structured-abstract fallback)
        # Paper 2: has structure -> 2 + 3 section texts = 5 texts
        # Total: 7 texts
        num_texts = 7

        async with respx.mock(assert_all_mocked=False) as respx_mock:
            fake_embeddings = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]] * num_texts
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(200, json={"embeddings": fake_embeddings}),
            )
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            embedder = PaperEmbedder(
                ollama_base_url="http://localhost:11434",
                target_dim=4,
            )

            papers = [
                (
                    "aaaa0001-0000-0000-0000-000000000000",
                    {"abstract": "Machine learning paper"},
                ),
                (
                    "aaaa0002-0000-0000-0000-000000000000",
                    {
                        "abstract": "Natural language processing",
                        "abstract_structure": {
                            "task": ["Classify text documents."],
                            "method": ["We use transformers for classification."],
                            "result": ["Our model achieves 95% accuracy."],
                        },
                    },
                ),
            ]

            async with embedder:
                count = await embedder.embed_and_upsert_batch(
                    papers=papers,
                    storage=storage,
                )

        assert count == 2

        # Verify vectors were stored for paper 1 (no structure)
        point1 = self.qdrant.retrieve(
            collection_name=self.collection,
            ids=["aaaa0001-0000-0000-0000-000000000000"],
            with_vectors=True,
            with_payload=True,
        )[0]
        assert EMBEDDING_VECTOR_NAME in point1.vector
        assert len(point1.vector[EMBEDDING_VECTOR_NAME]) == 4
        assert STRUCTURED_VECTOR_NAME in point1.vector
        # Paper 1 has no abstract_structure, so no section vectors
        assert point1.payload["title"] == "Paper 1"

        # Verify vectors for paper 2 (with structure)
        point2 = self.qdrant.retrieve(
            collection_name=self.collection,
            ids=["aaaa0002-0000-0000-0000-000000000000"],
            with_vectors=True,
            with_payload=True,
        )[0]
        assert EMBEDDING_VECTOR_NAME in point2.vector
        assert STRUCTURED_VECTOR_NAME in point2.vector
        # Paper 2 has task, method, result sections
        assert f"{SECTION_VECTOR_PREFIX}task" in point2.vector
        assert f"{SECTION_VECTOR_PREFIX}method" in point2.vector
        assert f"{SECTION_VECTOR_PREFIX}result" in point2.vector
        assert point2.payload["title"] == "Paper 2"

    @pytest.mark.asyncio
    async def test_embed_returns_zero_on_ollama_failure(self):
        from src.core.storage.base import QdrantStorage

        async with respx.mock(assert_all_mocked=False) as respx_mock:
            respx_mock.post("http://localhost:11434/api/embed").mock(
                return_value=Response(500, text="Server Error"),
            )
            respx_mock.route(host="localhost", port=6333).pass_through()

            storage = QdrantStorage(collection_name=self.collection)
            embedder = PaperEmbedder(
                ollama_base_url="http://localhost:11434",
                target_dim=4,
                max_retries=1,
            )

            papers = [
                ("aaaa0001-0000-0000-0000-000000000000", {"abstract": "Test"}),
            ]

            async with embedder:
                count = await embedder.embed_and_upsert_batch(
                    papers=papers,
                    storage=storage,
                )

        assert count == 0


@pytest.mark.integration
class TestEmbeddingIntegration:
    """End-to-end test: embed papers and verify hybrid search works.

    Requires: Ollama running with qwen3-embedding:8b pulled.
    Run with: uv run pytest tests/test_embedder.py -m integration -v
    """

    def setup_method(self):
        self.collection = "_test_e2e_embedding"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        vectors_config = {
            name: models.VectorParams(size=1024, distance=models.Distance.COSINE)
            for name in ALL_DENSE_VECTORS
        }
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=vectors_config,
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="e2e00001-0000-0000-0000-000000000001",
                    vector={},
                    payload={
                        "title": "Attention Is All You Need",
                        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
                        "is_stub": False,
                    },
                ),
                models.PointStruct(
                    id="e2e00001-0000-0000-0000-000000000002",
                    vector={},
                    payload={
                        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                        "abstract": "We introduce a new language representation model called BERT which stands for Bidirectional Encoder Representations from Transformers. BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context.",
                        "is_stub": False,
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
    async def test_embed_and_hybrid_search(self):
        from src.core.embedding.embedder import PaperEmbedder
        from src.core.storage.base import QdrantStorage

        storage = QdrantStorage(collection_name=self.collection)
        embedder = PaperEmbedder(target_dim=1024, max_concurrent=1)

        async with embedder:
            # Check model available
            if not await embedder.check_model_available():
                pytest.skip("Ollama qwen3-embedding:8b not available")

            # Embed papers
            papers = [
                ("e2e00001-0000-0000-0000-000000000001", {"abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms."}),
                ("e2e00001-0000-0000-0000-000000000002", {"abstract": "We introduce a new language representation model called BERT which stands for Bidirectional Encoder Representations from Transformers. BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context."}),
            ]
            count = await embedder.embed_and_upsert_batch(papers=papers, storage=storage)
            assert count == 2

            # Query: "transformer attention mechanism" should rank Attention paper first
            query_vectors = await embedder.embed_texts(["Retrieve academic papers: transformer attention mechanism"])
            assert query_vectors is not None

            results = self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    models.Prefetch(
                        query=query_vectors[0],
                        using="abstract-qwen3-8b",
                        limit=10,
                    ),
                    models.Prefetch(
                        query=models.Document(
                            text="transformer attention mechanism",
                            model="qdrant/bm25",
                        ),
                        using="bm25",
                        limit=10,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=2,
                with_payload=True,
            )

            assert len(results.points) == 2
            # Attention paper should rank first for "transformer attention mechanism"
            assert results.points[0].payload["title"] == "Attention Is All You Need"
