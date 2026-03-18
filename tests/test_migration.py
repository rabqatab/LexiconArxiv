from qdrant_client import QdrantClient, models
from src.core.storage.base import QdrantStorage


class TestEnsureCollectionWithVectors:
    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        self.collection = "_test_ensure_vectors"
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def test_creates_collection_with_dense_and_sparse_vectors(self):
        storage = QdrantStorage(collection_name=self.collection)
        created = storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        assert created is True
        info = self.client.get_collection(self.collection)
        assert "abstract-qwen3-8b" in info.config.params.vectors
        assert info.config.params.vectors["abstract-qwen3-8b"].size == 1024
        assert info.config.params.vectors["abstract-qwen3-8b"].distance == models.Distance.COSINE

    def test_returns_false_if_collection_already_exists(self):
        storage = QdrantStorage(collection_name=self.collection)
        storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        created = storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        assert created is False


class TestGetPapersForEmbedding:
    def setup_method(self):
        self.collection = "_test_embed_reader"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(size=4, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 1", "abstract": "Has abstract", "is_stub": False},
                ),
                models.PointStruct(
                    id="aaaa0002-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Stub", "abstract": "Stub abstract", "is_stub": True},
                ),
                models.PointStruct(
                    id="aaaa0003-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "No abstract", "abstract": "", "is_stub": False},
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def test_returns_non_stub_papers_with_abstracts(self):
        storage = QdrantStorage(collection_name=self.collection)
        papers, next_offset = storage.get_papers_for_embedding(limit=10)
        assert len(papers) == 1
        point_id, payload = papers[0]
        assert payload["title"] == "Paper 1"
