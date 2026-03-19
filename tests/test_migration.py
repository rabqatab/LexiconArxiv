from qdrant_client import QdrantClient, models
from src.core.storage.base import QdrantStorage
from src.core.embedding.migration import CollectionMigrator
from src.core.constants import ALL_DENSE_VECTORS


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

    def test_creates_collection_with_all_dense_and_sparse_vectors(self):
        storage = QdrantStorage(collection_name=self.collection)
        created = storage.ensure_collection_with_vectors(dense_vector_size=1024)
        assert created is True
        info = self.client.get_collection(self.collection)
        # Should have all 9 dense vectors
        for name in ALL_DENSE_VECTORS:
            assert name in info.config.params.vectors, f"Missing vector: {name}"
            assert info.config.params.vectors[name].size == 1024
            assert info.config.params.vectors[name].distance == models.Distance.COSINE

    def test_returns_false_if_collection_already_exists(self):
        storage = QdrantStorage(collection_name=self.collection)
        storage.ensure_collection_with_vectors(dense_vector_size=1024)
        created = storage.ensure_collection_with_vectors(dense_vector_size=1024)
        assert created is False


class TestGetPapersForEmbedding:
    def setup_method(self):
        self.collection = "_test_embed_reader"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        vectors_config = {
            name: models.VectorParams(size=4, distance=models.Distance.COSINE)
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
                    id="aaaa0001-0000-0000-0000-000000000000",
                    vector={},
                    payload={
                        "title": "Paper 1",
                        "abstract": "Has abstract",
                        "is_stub": False,
                        "abstract_structure": {"task": ["Do something."]},
                    },
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

    def test_returns_abstract_structure_in_payload(self):
        storage = QdrantStorage(collection_name=self.collection)
        papers, _ = storage.get_papers_for_embedding(limit=10)
        assert len(papers) == 1
        _, payload = papers[0]
        assert "abstract_structure" in payload
        assert payload["abstract_structure"]["task"] == ["Do something."]


class TestCollectionMigrator:
    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        self.old_name = "_test_old_collection"
        self.new_name = "_test_new_collection"
        for name in [self.old_name, self.new_name]:
            try:
                self.client.delete_collection(name)
            except Exception:
                pass

    def teardown_method(self):
        for name in [self.old_name, self.new_name]:
            try:
                self.client.delete_collection(name)
            except Exception:
                pass

    def test_migrates_points_preserving_ids_and_payloads(self):
        # Create old payload-only collection
        self.client.create_collection(
            collection_name=self.old_name,
            vectors_config={},
        )
        self.client.upsert(
            collection_name=self.old_name,
            points=[
                models.PointStruct(
                    id="aaaaaaaa-1111-2222-3333-444444444444",
                    vector={},
                    payload={"title": "Test Paper 1", "abstract": "About ML", "is_core": True},
                ),
                models.PointStruct(
                    id="bbbbbbbb-1111-2222-3333-444444444444",
                    vector={},
                    payload={"title": "Test Paper 2", "abstract": "About NLP", "is_stub": True},
                ),
            ],
        )

        migrator = CollectionMigrator(
            url="http://localhost:6333",
            old_collection=self.old_name,
            new_collection=self.new_name,
        )
        stats = migrator.migrate()

        assert stats["points_migrated"] == 2

        # Verify new collection has ALL dense vector configs
        info = self.client.get_collection(self.new_name)
        for name in ALL_DENSE_VECTORS:
            assert name in info.config.params.vectors, f"Missing vector: {name}"

        # Verify points preserved
        result = self.client.scroll(self.new_name, limit=10, with_payload=True)
        points = result[0]
        assert len(points) == 2
        ids = {str(p.id) for p in points}
        assert "aaaaaaaa-1111-2222-3333-444444444444" in ids
        payloads = {p.payload["title"] for p in points}
        assert "Test Paper 1" in payloads
        assert "Test Paper 2" in payloads

    def test_migrates_preserving_existing_vectors(self):
        """When old collection has vectors, they should be preserved in migration."""
        # Create old collection with one dense vector config
        self.client.create_collection(
            collection_name=self.old_name,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(
                    size=4, distance=models.Distance.COSINE,
                ),
            },
        )
        self.client.upsert(
            collection_name=self.old_name,
            points=[
                models.PointStruct(
                    id="aaaaaaaa-1111-2222-3333-444444444444",
                    vector={"abstract-qwen3-8b": [0.1, 0.2, 0.3, 0.4]},
                    payload={"title": "Paper with vector"},
                ),
            ],
        )

        migrator = CollectionMigrator(
            url="http://localhost:6333",
            old_collection=self.old_name,
            new_collection=self.new_name,
        )
        stats = migrator.migrate(dense_vector_size=4)

        assert stats["points_migrated"] == 1

        # Verify the existing vector was preserved
        points = self.client.retrieve(
            collection_name=self.new_name,
            ids=["aaaaaaaa-1111-2222-3333-444444444444"],
            with_vectors=True,
        )
        assert len(points) == 1
        vec = points[0].vector.get("abstract-qwen3-8b")
        assert vec is not None
        assert len(vec) == 4
        # Qdrant normalizes COSINE vectors; check proportions are preserved
        assert vec[0] > 0  # Non-zero
        assert abs(vec[1] / vec[0] - 2.0) < 0.01  # 0.2/0.1 = 2.0
