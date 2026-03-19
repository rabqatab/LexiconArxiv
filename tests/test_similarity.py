"""Tests for semantic similarity graph computation."""

import pytest
from qdrant_client import QdrantClient, models

from src.core.analytics.similarity import (
    EDGE_TYPES,
    compute_similarity_batch,
    compute_similarity_for_paper,
)
from src.core.constants import (
    EMBEDDING_VECTOR_SIZE,
    SECTION_VECTOR_PREFIX,
    STRUCTURED_VECTOR_NAME,
)
from src.core.storage.base import QdrantStorage


TEST_COLLECTION = "_test_similarity"

# Vector names used in tests
VEC_METHOD = f"{SECTION_VECTOR_PREFIX}method"
VEC_TASK = f"{SECTION_VECTOR_PREFIX}task"
VEC_RESULT = f"{SECTION_VECTOR_PREFIX}result"
VEC_STRUCTURED = STRUCTURED_VECTOR_NAME

DIM = EMBEDDING_VECTOR_SIZE


def _unit_vector(seed: int, dim: int = DIM) -> list[float]:
    """Create a simple deterministic vector for testing."""
    import math

    raw = [(seed * (i + 1) % 97) / 97.0 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    if norm == 0:
        raw[0] = 1.0
        norm = 1.0
    return [x / norm for x in raw]


class TestSimilarityGraph:
    """Tests for similarity graph computation with a real Qdrant collection."""

    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass

        # Create collection with required named vectors
        vectors_config = {}
        for vec_name in [VEC_METHOD, VEC_TASK, VEC_RESULT, VEC_STRUCTURED]:
            vectors_config[vec_name] = models.VectorParams(
                size=DIM,
                distance=models.Distance.COSINE,
            )

        self.client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config=vectors_config,
        )

        # Paper A: has all vectors
        self.paper_a_id = "aaaa0001-0000-0000-0000-000000000001"
        # Paper B: similar to A (same seed family)
        self.paper_b_id = "aaaa0001-0000-0000-0000-000000000002"
        # Paper C: different vectors
        self.paper_c_id = "aaaa0001-0000-0000-0000-000000000003"
        # Paper D: stub — should be excluded
        self.paper_d_id = "aaaa0001-0000-0000-0000-000000000004"

        self.client.upsert(
            collection_name=TEST_COLLECTION,
            points=[
                models.PointStruct(
                    id=self.paper_a_id,
                    vector={
                        VEC_METHOD: _unit_vector(1),
                        VEC_TASK: _unit_vector(2),
                        VEC_RESULT: _unit_vector(3),
                        VEC_STRUCTURED: _unit_vector(4),
                    },
                    payload={
                        "title": "Paper A",
                        "venue": "NeurIPS",
                        "year": 2024,
                    },
                ),
                models.PointStruct(
                    id=self.paper_b_id,
                    vector={
                        VEC_METHOD: _unit_vector(1),  # Same method as A
                        VEC_TASK: _unit_vector(2),    # Same task as A
                        VEC_RESULT: _unit_vector(5),  # Different result
                        VEC_STRUCTURED: _unit_vector(4),  # Same structured as A
                    },
                    payload={
                        "title": "Paper B",
                        "venue": "ICML",
                        "year": 2023,
                    },
                ),
                models.PointStruct(
                    id=self.paper_c_id,
                    vector={
                        VEC_METHOD: _unit_vector(50),
                        VEC_TASK: _unit_vector(60),
                        VEC_RESULT: _unit_vector(70),
                        VEC_STRUCTURED: _unit_vector(80),
                    },
                    payload={
                        "title": "Paper C",
                        "venue": "AAAI",
                        "year": 2022,
                    },
                ),
                models.PointStruct(
                    id=self.paper_d_id,
                    vector={
                        VEC_METHOD: _unit_vector(1),  # Same as A
                        VEC_TASK: _unit_vector(2),
                        VEC_RESULT: _unit_vector(3),
                        VEC_STRUCTURED: _unit_vector(4),
                    },
                    payload={
                        "title": "Stub Paper",
                        "venue": "NeurIPS",
                        "year": 2024,
                        "is_stub": True,
                    },
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass

    def test_compute_similarity_for_paper_returns_structure(self):
        """Result should be dict of edge_type -> list of neighbor dicts."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_TASK: _unit_vector(2),
            VEC_RESULT: _unit_vector(3),
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=5,
        )

        assert isinstance(results, dict)
        for edge_name in results:
            assert edge_name in EDGE_TYPES
            neighbors = results[edge_name]
            assert isinstance(neighbors, list)
            for n in neighbors:
                assert "id" in n
                assert "score" in n
                assert "title" in n

    def test_self_excluded_from_neighbors(self):
        """Paper A should not appear in its own similarity results."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_TASK: _unit_vector(2),
            VEC_RESULT: _unit_vector(3),
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=10,
        )

        all_ids = []
        for neighbors in results.values():
            all_ids.extend(n["id"] for n in neighbors)

        assert self.paper_a_id not in all_ids

    def test_stubs_excluded_from_neighbors(self):
        """Stub papers should not appear in similarity results."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_TASK: _unit_vector(2),
            VEC_RESULT: _unit_vector(3),
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=10,
        )

        all_ids = []
        for neighbors in results.values():
            all_ids.extend(n["id"] for n in neighbors)

        assert self.paper_d_id not in all_ids

    def test_same_method_finds_similar_paper(self):
        """Paper B has same method vector as A, should appear in same_method."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_TASK: _unit_vector(2),
            VEC_RESULT: _unit_vector(3),
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=5,
        )

        assert "same_method" in results
        method_ids = [n["id"] for n in results["same_method"]]
        assert self.paper_b_id in method_ids

    def test_neighbor_metadata_populated(self):
        """Neighbors should have title, venue, year metadata."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=5,
        )

        for edge_name, neighbors in results.items():
            for n in neighbors:
                assert n["title"] != ""
                assert n["venue"] is not None
                assert n["year"] is not None

    def test_missing_vectors_skipped(self):
        """Edge types with no source vector should be skipped gracefully."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        # Only provide structured vector, not section vectors
        vectors = {
            VEC_STRUCTURED: _unit_vector(4),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=5,
        )

        # Should only have "overall" since that's the only one with a vector
        assert "overall" in results
        assert "same_method" not in results
        assert "same_task" not in results
        assert "same_result" not in results

    def test_custom_edge_types(self):
        """Custom edge_types should limit which edges are computed."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        vectors = {
            VEC_METHOD: _unit_vector(1),
            VEC_TASK: _unit_vector(2),
            VEC_RESULT: _unit_vector(3),
            VEC_STRUCTURED: _unit_vector(4),
        }

        custom_types = {
            "overall": (VEC_STRUCTURED, VEC_STRUCTURED),
        }

        results = compute_similarity_for_paper(
            storage=storage,
            paper_id=self.paper_a_id,
            paper_vectors=vectors,
            k=5,
            edge_types=custom_types,
        )

        assert "overall" in results
        assert len(results) == 1

    def test_compute_similarity_batch_processes_and_stores(self):
        """Batch computation should process papers and store results."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)

        stats = compute_similarity_batch(
            storage=storage,
            k=5,
            batch_size=10,
        )

        assert stats["processed"] > 0
        assert stats["updated"] > 0
        assert "elapsed_seconds" in stats
        assert stats["k"] == 5
        assert isinstance(stats["edge_types"], list)

        # Verify results were stored in payload
        points = self.client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[self.paper_a_id],
            with_payload=["similar_papers"],
        )
        assert len(points) == 1
        similar = points[0].payload.get("similar_papers", {})
        assert isinstance(similar, dict)
        assert len(similar) > 0

    def test_compute_similarity_batch_limit(self):
        """Batch with limit should stop early."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)

        stats = compute_similarity_batch(
            storage=storage,
            k=5,
            batch_size=1,
            limit=1,
        )

        assert stats["processed"] <= 1

    def test_compute_similarity_batch_excludes_stubs(self):
        """Batch should not process stub papers."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)

        stats = compute_similarity_batch(
            storage=storage,
            k=5,
            batch_size=10,
        )

        # We have 3 non-stub papers with structured-abstract vector, 1 stub
        assert stats["processed"] == 3

    def test_empty_collection(self):
        """Batch on empty collection should return zero counts."""
        empty_collection = "_test_similarity_empty"
        try:
            self.client.delete_collection(empty_collection)
        except Exception:
            pass
        self.client.create_collection(
            collection_name=empty_collection,
            vectors_config={
                VEC_STRUCTURED: models.VectorParams(
                    size=DIM,
                    distance=models.Distance.COSINE,
                ),
            },
        )

        try:
            storage = QdrantStorage(collection_name=empty_collection)
            stats = compute_similarity_batch(
                storage=storage,
                k=5,
                batch_size=10,
            )
            assert stats["processed"] == 0
            assert stats["updated"] == 0
        finally:
            self.client.delete_collection(empty_collection)
