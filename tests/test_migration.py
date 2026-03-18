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
