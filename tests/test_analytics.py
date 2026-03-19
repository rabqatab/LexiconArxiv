"""Tests for analytics modules: notable paper scoring, keyword trends, and clustering."""

import math

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from src.core.analytics.notable import (
    CURRENT_YEAR,
    _recency_boost,
    _tier_boost,
    get_notable_papers,
)
from src.core.analytics.keyword_trends import (
    CURRENT_YEAR as KW_CURRENT_YEAR,
    compute_keyword_trends,
    get_rising_keywords,
)
from src.core.analytics.clustering import (
    _build_cluster_metadata,
    compute_clusters,
)
from src.core.storage.base import QdrantStorage


TEST_COLLECTION = "_test_analytics"


def _make_point(pid: str, payload: dict) -> models.PointStruct:
    return models.PointStruct(id=pid, vector={}, payload=payload)


class TestNotableScoring:
    """Tests for notable paper scoring."""

    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass
        self.client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config={},
        )

        # Insert test papers with known values
        self.client.upsert(
            collection_name=TEST_COLLECTION,
            points=[
                # Paper A: high citations, high pagerank, recent, tier 0
                _make_point(
                    "aaaa0001-0000-0000-0000-000000000001",
                    {
                        "title": "Top Paper",
                        "citation_count": 1000,
                        "pagerank": 0.9,
                        "year": CURRENT_YEAR,
                        "tier": 0,
                        "venue": "NeurIPS",
                        "doi": "10.1/a",
                        "authors": ["Alice"],
                    },
                ),
                # Paper B: moderate citations, moderate pagerank, older, tier 1
                _make_point(
                    "aaaa0001-0000-0000-0000-000000000002",
                    {
                        "title": "Mid Paper",
                        "citation_count": 500,
                        "pagerank": 0.5,
                        "year": 2021,
                        "tier": 1,
                        "venue": "AAAI",
                        "doi": "10.1/b",
                        "authors": ["Bob"],
                    },
                ),
                # Paper C: low citations, low pagerank, old, tier 2
                _make_point(
                    "aaaa0001-0000-0000-0000-000000000003",
                    {
                        "title": "Low Paper",
                        "citation_count": 10,
                        "pagerank": 0.05,
                        "year": 2019,
                        "tier": 2,
                        "venue": "Workshop",
                        "doi": "10.1/c",
                        "authors": ["Carol"],
                    },
                ),
                # Paper D: zero citations, no pagerank, no tier (None)
                _make_point(
                    "aaaa0001-0000-0000-0000-000000000004",
                    {
                        "title": "Unknown Paper",
                        "citation_count": 0,
                        "pagerank": 0.0,
                        "year": 2020,
                        "venue": "Unknown",
                        "doi": "10.1/d",
                        "authors": ["Dave"],
                    },
                ),
                # Stub paper: should be excluded
                _make_point(
                    "aaaa0001-0000-0000-0000-000000000005",
                    {
                        "title": "Stub Paper",
                        "is_stub": True,
                        "citation_count": 9999,
                        "pagerank": 1.0,
                        "year": CURRENT_YEAR,
                        "tier": 0,
                    },
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass

    def test_recency_boost_current_year(self):
        assert _recency_boost(CURRENT_YEAR) == 1.0

    def test_recency_boost_base_year(self):
        assert _recency_boost(2019) == 0.0

    def test_recency_boost_clamped_below(self):
        assert _recency_boost(2015) == 0.0

    def test_recency_boost_none(self):
        assert _recency_boost(None) == 0.0

    def test_tier_boost_values(self):
        assert _tier_boost(0) == 1.0
        assert _tier_boost(1) == 0.7
        assert _tier_boost(2) == 0.4
        assert _tier_boost(None) == 0.3

    def test_notable_papers_ranking_order(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=10)

        titles = [r["title"] for r in results]
        # Paper A (high everything) should be first
        assert titles[0] == "Top Paper"
        # Stub should not appear
        assert "Stub Paper" not in titles
        # All 4 non-stub papers should appear
        assert len(results) == 4

    def test_high_citations_recent_beats_low(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=10)

        scores = {r["title"]: r["notable_score"] for r in results}
        assert scores["Top Paper"] > scores["Low Paper"]
        assert scores["Top Paper"] > scores["Unknown Paper"]

    def test_notable_papers_limit(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=2)
        assert len(results) == 2

    def test_notable_papers_year_filter(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=10, year_min=2021)

        years = [r["year"] for r in results]
        assert all(y >= 2021 for y in years)
        # Paper C (2019) and Paper D (2020) excluded
        assert len(results) == 2

    def test_notable_papers_year_max_filter(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=10, year_max=2020)

        years = [r["year"] for r in results]
        assert all(y <= 2020 for y in years)

    def test_notable_papers_tier_filter(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=10, tiers=[0])

        # Only Paper A has tier 0
        assert len(results) == 1
        assert results[0]["title"] == "Top Paper"

    def test_notable_papers_excludes_stubs(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        results = get_notable_papers(storage, limit=100)

        titles = [r["title"] for r in results]
        assert "Stub Paper" not in titles

    def test_notable_score_components(self):
        """Verify the scoring formula with known weights."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        # Use equal weights for easy verification
        results = get_notable_papers(
            storage, limit=10, weights=(0.25, 0.25, 0.25, 0.25)
        )

        top = results[0]
        assert top["title"] == "Top Paper"
        # Top Paper: norm_cit=1.0, norm_pr=1.0, recency=1.0, tier=1.0
        expected = 0.25 * 1.0 + 0.25 * 1.0 + 0.25 * 1.0 + 0.25 * 1.0
        assert abs(top["notable_score"] - expected) < 1e-9

    def test_empty_collection(self):
        """Test with a collection that has no matching papers."""
        empty_collection = "_test_analytics_empty"
        try:
            self.client.delete_collection(empty_collection)
        except Exception:
            pass
        self.client.create_collection(
            collection_name=empty_collection,
            vectors_config={},
        )
        try:
            storage = QdrantStorage(collection_name=empty_collection)
            results = get_notable_papers(storage, limit=10)
            assert results == []
        finally:
            self.client.delete_collection(empty_collection)


class TestKeywordTrends:
    """Tests for keyword trend analysis."""

    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass
        self.client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config={},
        )

        # Recent years (last 2): CURRENT_YEAR, CURRENT_YEAR-1
        # Older years (2 before that): CURRENT_YEAR-2, CURRENT_YEAR-3
        yr = KW_CURRENT_YEAR

        points = []
        pid = 0

        # "llm" keyword: 6 in recent, 2 in older => growth_rate = 3.0
        for _ in range(3):
            pid += 1
            points.append(_make_point(
                f"bbbb0001-0000-0000-0000-{pid:012d}",
                {
                    "title": f"LLM Paper Recent {pid}",
                    "year": yr,
                    "keywords_structured": {
                        "method": ["llm"],
                        "task": ["text generation"],
                    },
                },
            ))
        for _ in range(3):
            pid += 1
            points.append(_make_point(
                f"bbbb0001-0000-0000-0000-{pid:012d}",
                {
                    "title": f"LLM Paper Recent-1 {pid}",
                    "year": yr - 1,
                    "keywords_structured": {
                        "method": ["llm"],
                        "task": ["text generation"],
                    },
                },
            ))
        for _ in range(2):
            pid += 1
            points.append(_make_point(
                f"bbbb0001-0000-0000-0000-{pid:012d}",
                {
                    "title": f"LLM Paper Older {pid}",
                    "year": yr - 2,
                    "keywords_structured": {
                        "method": ["llm"],
                        "task": ["text generation"],
                    },
                },
            ))

        # "cnn" keyword: 1 in recent, 4 in older => growth_rate = 0.25
        pid += 1
        points.append(_make_point(
            f"bbbb0001-0000-0000-0000-{pid:012d}",
            {
                "title": f"CNN Paper Recent {pid}",
                "year": yr,
                "keywords_structured": {
                    "method": ["cnn"],
                    "task": ["image classification"],
                },
            },
        ))
        for _ in range(4):
            pid += 1
            points.append(_make_point(
                f"bbbb0001-0000-0000-0000-{pid:012d}",
                {
                    "title": f"CNN Paper Older {pid}",
                    "year": yr - 3,
                    "keywords_structured": {
                        "method": ["cnn"],
                        "task": ["image classification"],
                    },
                },
            ))

        # "rag" keyword: only 2 papers total (below min_count=5 default)
        for _ in range(2):
            pid += 1
            points.append(_make_point(
                f"bbbb0001-0000-0000-0000-{pid:012d}",
                {
                    "title": f"RAG Paper {pid}",
                    "year": yr,
                    "keywords_structured": {
                        "method": ["rag"],
                    },
                },
            ))

        # Stub paper: should be excluded
        pid += 1
        points.append(_make_point(
            f"bbbb0001-0000-0000-0000-{pid:012d}",
            {
                "title": "Stub KW Paper",
                "is_stub": True,
                "year": yr,
                "keywords_structured": {
                    "method": ["stub_method"],
                    "task": ["stub_task"],
                },
            },
        ))

        self.client.upsert(collection_name=TEST_COLLECTION, points=points)

    def teardown_method(self):
        try:
            self.client.delete_collection(TEST_COLLECTION)
        except Exception:
            pass

    def test_compute_keyword_trends_growth_rate(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=5)

        kw_map = {t["keyword"]: t for t in trends}
        assert "llm" in kw_map
        assert "cnn" in kw_map

        # LLM: 6 recent / 2 older = 3.0
        assert kw_map["llm"]["count_recent"] == 6
        assert kw_map["llm"]["count_older"] == 2
        assert abs(kw_map["llm"]["growth_rate"] - 3.0) < 1e-9

        # CNN: 1 recent / 4 older = 0.25
        assert kw_map["cnn"]["count_recent"] == 1
        assert kw_map["cnn"]["count_older"] == 4
        assert abs(kw_map["cnn"]["growth_rate"] - 0.25) < 1e-9

    def test_min_count_filters_rare_keywords(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=5)

        kw_names = {t["keyword"] for t in trends}
        # "rag" only has 2 papers, should be excluded at min_count=5
        assert "rag" not in kw_names

    def test_min_count_includes_when_low_enough(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=2)

        kw_names = {t["keyword"] for t in trends}
        assert "rag" in kw_names

    def test_trends_sorted_by_growth_rate(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=5)

        growth_rates = [t["growth_rate"] for t in trends]
        assert growth_rates == sorted(growth_rates, reverse=True)

    def test_excludes_stub_papers(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=1)

        kw_names = {t["keyword"] for t in trends}
        assert "stub_method" not in kw_names

    def test_category_filter(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="task", min_count=5)

        categories = {t["category"] for t in trends}
        assert categories == {"task"}

    def test_all_categories(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category=None, min_count=5)

        categories = {t["category"] for t in trends}
        # Should include both "method" and "task" categories
        assert "method" in categories
        assert "task" in categories

    def test_yearly_counts_dict(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        trends = compute_keyword_trends(storage, category="method", min_count=5)

        kw_map = {t["keyword"]: t for t in trends}
        llm_yearly = kw_map["llm"]["yearly_counts"]
        assert isinstance(llm_yearly, dict)
        assert llm_yearly[KW_CURRENT_YEAR] == 3
        assert llm_yearly[KW_CURRENT_YEAR - 1] == 3
        assert llm_yearly[KW_CURRENT_YEAR - 2] == 2

    def test_get_rising_keywords_top_k(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        rising = get_rising_keywords(storage, top_k=1, category="method", min_count=5)

        assert len(rising) == 1
        # LLM has higher growth rate than CNN
        assert rising[0]["keyword"] == "llm"

    def test_get_rising_keywords_sorted(self):
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        rising = get_rising_keywords(storage, top_k=10, category="method", min_count=5)

        growth_rates = [r["growth_rate"] for r in rising]
        assert growth_rates == sorted(growth_rates, reverse=True)

    def test_growth_rate_inf_when_no_older(self):
        """Keywords with recent papers but no older ones get inf growth rate."""
        storage = QdrantStorage(collection_name=TEST_COLLECTION)
        # "rag" has 2 papers only in current year, no older => inf growth
        trends = compute_keyword_trends(storage, category="method", min_count=1)

        kw_map = {t["keyword"]: t for t in trends}
        assert "rag" in kw_map
        assert kw_map["rag"]["count_older"] == 0
        assert kw_map["rag"]["count_recent"] > 0
        assert math.isinf(kw_map["rag"]["growth_rate"])


class TestBuildClusterMetadata:
    """Tests for _build_cluster_metadata with synthetic data."""

    def test_basic_cluster_metadata(self):
        labels = np.array([0, 0, 1, 1, 1, -1])
        metadata = [
            {"year": 2023, "keywords_structured": {"method": ["transformer", "llm"]}},
            {"year": 2024, "keywords_structured": {"method": ["transformer"]}},
            {"year": 2022, "keywords_structured": {"task": ["image classification"]}},
            {"year": 2023, "keywords_structured": {"task": ["image classification", "object detection"]}},
            {"year": 2023, "keywords_structured": {"task": ["image classification"]}},
            {"year": 2024, "keywords_structured": {"method": ["noise"]}},  # noise point
        ]
        clusters = _build_cluster_metadata(labels, metadata)

        assert len(clusters) == 2

        c0 = next(c for c in clusters if c["cluster_id"] == 0)
        assert c0["size"] == 2
        assert "transformer" in c0["top_keywords"]
        assert "2023" in c0["year_distribution"]
        assert "2024" in c0["year_distribution"]

        c1 = next(c for c in clusters if c["cluster_id"] == 1)
        assert c1["size"] == 3
        assert "image classification" in c1["top_keywords"]

    def test_label_from_top_keywords(self):
        labels = np.array([0, 0, 0])
        metadata = [
            {"keywords_structured": {"method": ["aaa", "bbb"]}},
            {"keywords_structured": {"method": ["aaa", "ccc"]}},
            {"keywords_structured": {"method": ["aaa"]}},
        ]
        clusters = _build_cluster_metadata(labels, metadata)

        assert len(clusters) == 1
        # "aaa" appears 3 times so should be first in label
        assert clusters[0]["label"].startswith("aaa")

    def test_fallback_to_flat_keywords(self):
        labels = np.array([0, 0])
        metadata = [
            {"keywords": ["flat_kw1", "flat_kw2"]},
            {"keywords": ["flat_kw1"]},
        ]
        clusters = _build_cluster_metadata(labels, metadata)

        assert len(clusters) == 1
        assert "flat_kw1" in clusters[0]["top_keywords"]

    def test_no_clusters_when_all_noise(self):
        labels = np.array([-1, -1, -1])
        metadata = [{"year": 2023}] * 3
        clusters = _build_cluster_metadata(labels, metadata)

        assert clusters == []

    def test_empty_metadata(self):
        labels = np.array([0, 0])
        metadata = [{}, {}]
        clusters = _build_cluster_metadata(labels, metadata)

        assert len(clusters) == 1
        assert clusters[0]["size"] == 2
        assert clusters[0]["label"] == "Cluster 0"
        assert clusters[0]["top_keywords"] == []

    def test_year_distribution(self):
        labels = np.array([0, 0, 0, 0])
        metadata = [
            {"year": 2022},
            {"year": 2022},
            {"year": 2023},
            {"year": 2024},
        ]
        clusters = _build_cluster_metadata(labels, metadata)

        year_dist = clusters[0]["year_distribution"]
        assert year_dist["2022"] == 2
        assert year_dist["2023"] == 1
        assert year_dist["2024"] == 1


class TestComputeClusters:
    """Tests for compute_clusters with too few vectors."""

    CLUSTER_TEST_COLLECTION = "_test_clustering"

    def setup_method(self):
        from src.core.constants import EMBEDDING_VECTOR_NAME, EMBEDDING_VECTOR_SIZE

        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.CLUSTER_TEST_COLLECTION)
        except Exception:
            pass
        # Create collection with vector config so scroll with_vectors works
        self.client.create_collection(
            collection_name=self.CLUSTER_TEST_COLLECTION,
            vectors_config={
                EMBEDDING_VECTOR_NAME: models.VectorParams(
                    size=EMBEDDING_VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            },
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.CLUSTER_TEST_COLLECTION)
        except Exception:
            pass

    def test_too_few_vectors_returns_error(self):
        """compute_clusters returns error when collection is empty."""
        storage = QdrantStorage(collection_name=self.CLUSTER_TEST_COLLECTION)
        result = compute_clusters(
            storage=storage,
            hdbscan_min_cluster_size=50,
        )

        assert "error" in result
        assert result["count"] == 0

    def test_too_few_vectors_with_some_papers(self):
        """compute_clusters returns error when too few papers have vectors."""
        vec_collection = "_test_clustering_vec"
        try:
            self.client.delete_collection(vec_collection)
        except Exception:
            pass

        # Create collection with vector config so scroll with_vectors works
        from src.core.constants import EMBEDDING_VECTOR_NAME, EMBEDDING_VECTOR_SIZE

        self.client.create_collection(
            collection_name=vec_collection,
            vectors_config={
                EMBEDDING_VECTOR_NAME: models.VectorParams(
                    size=EMBEDDING_VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            },
        )

        # Insert a few papers with actual vectors (but too few for clustering)
        dim = EMBEDDING_VECTOR_SIZE
        points = [
            models.PointStruct(
                id=f"cccc0001-0000-0000-0000-{i:012d}",
                vector={EMBEDDING_VECTOR_NAME: [float(i)] * dim},
                payload={"title": f"Paper {i}", "year": 2023},
            )
            for i in range(5)
        ]
        self.client.upsert(collection_name=vec_collection, points=points)

        try:
            storage = QdrantStorage(collection_name=vec_collection)
            result = compute_clusters(
                storage=storage,
                hdbscan_min_cluster_size=50,
            )

            assert "error" in result
            assert result["count"] == 5
        finally:
            self.client.delete_collection(vec_collection)
