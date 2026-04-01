# Testing Strategy

## 1. Overview

This document defines the testing strategy and quality assurance methodology for the AI/NLP paper search engine.

---

## 2. Testing Pyramid

```
                    ┌─────────┐
                    │   E2E   │  ← 10%
                    │  Tests  │
                 ┌──┴─────────┴──┐
                 │  Integration  │  ← 30%
                 │    Tests      │
              ┌──┴───────────────┴──┐
              │     Unit Tests      │  ← 60%
              └─────────────────────┘
```

---

## 3. Unit Tests

### 3.1 Coverage Targets

| Module | Target Coverage | Critical Paths |
|--------|----------------|----------------|
| Query Planner | 90% | Entity extraction, query expansion |
| Deduplicator | 95% | DOI matching, fuzzy matching |
| Score Fusion | 90% | RRF, weighted fusion |
| Keyword Extractor | 90% | Regex patterns, KeyBERT, stopword filtering |
| Data Normalizer | 85% | Title normalization, author parsing |
| API Validators | 95% | Input validation, error handling |

### 3.2 Query Planner Tests

```python
# tests/unit/test_query_planner.py

class TestQueryAnalyzer:
    def test_detects_year_entity(self):
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("papers from 2024")

        assert any(
            e.type == EntityType.YEAR and e.normalized == "2024"
            for e in result.detected_entities
        )

    def test_detects_venue_entity(self):
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("ACL 2023 summarization")

        venues = [e for e in result.detected_entities if e.type == EntityType.VENUE]
        assert len(venues) == 1
        assert venues[0].normalized == "ACL"

    def test_detects_paper_type(self):
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("instruction tuning datasets")

        types = [e for e in result.detected_entities if e.type == EntityType.PAPER_TYPE]
        assert len(types) == 1
        assert types[0].normalized == "dataset"

    def test_handles_korean_query(self):
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("Korean LLM papers")

        assert result.language == "ko"

    def test_query_expansion_synonyms(self):
        expander = QueryExpander()
        analysis = QueryAnalysis(
            original_query="RAG papers",
            detected_entities=[Entity(text="RAG", type=EntityType.TOPIC)]
        )

        expanded = expander.expand(analysis)

        assert "retrieval augmented generation" in expanded.expansions


class TestSearchStrategySelector:
    def test_discovery_query_uses_all_sources(self):
        selector = SearchStrategySelector()
        analysis = QueryAnalysis(query_type=QueryType.DISCOVERY)

        strategy = selector.select(analysis)

        assert "openalex" in strategy.external_sources
        assert "arxiv" in strategy.external_sources
        assert "acl" in strategy.external_sources

    def test_monitoring_query_prioritizes_arxiv(self):
        selector = SearchStrategySelector()
        analysis = QueryAnalysis(query_type=QueryType.MONITORING)

        strategy = selector.select(analysis)

        assert strategy.external_sources == ["arxiv"]
        assert strategy.fusion_method == "recency_boost"
```

### 3.3 Deduplicator Tests

```python
# tests/unit/test_deduplicator.py

class TestDeduplicator:
    def test_exact_doi_match(self):
        dedup = Deduplicator()
        papers = [
            RawPaper(doi="10.1234/paper1", title="Paper A", source="openalex"),
            RawPaper(doi="10.1234/paper1", title="Paper A", source="arxiv"),
        ]

        result = dedup.dedupe(papers)

        assert len(result) == 1
        assert len(result[0].source_records) == 2

    def test_arxiv_id_match(self):
        dedup = Deduplicator()
        papers = [
            RawPaper(arxiv_id="2304.12345", title="Paper A", source="arxiv"),
            RawPaper(arxiv_id="2304.12345", title="Paper A", source="openalex"),
        ]

        result = dedup.dedupe(papers)

        assert len(result) == 1

    def test_fuzzy_title_match(self):
        dedup = Deduplicator()
        papers = [
            RawPaper(
                title="KULLM: Korean Large Language Model",
                year=2023,
                authors=[{"name": "Kim"}],
                source="arxiv"
            ),
            RawPaper(
                title="KULLM: Korean Large Language Model",
                year=2023,
                authors=[{"name": "Kim, S."}],
                source="openalex"
            ),
        ]

        result = dedup.dedupe(papers)

        assert len(result) == 1

    def test_different_year_not_matched(self):
        dedup = Deduplicator()
        papers = [
            RawPaper(title="Same Title", year=2022, source="arxiv"),
            RawPaper(title="Same Title", year=2023, source="openalex"),
        ]

        result = dedup.dedupe(papers)

        assert len(result) == 2

    def test_title_normalization(self):
        dedup = Deduplicator()

        assert dedup._normalize_title("KULLM: Korean LLM") == "kullm korean llm"
        assert dedup._normalize_title("KULLM:  Korean  LLM") == "kullm korean llm"
        assert dedup._normalize_title("KULLM - Korean LLM") == "kullm korean llm"
```

### 3.4 Keyword Extraction Tests

See [Keyword Extraction Pipeline](../pipelines/keyword_extraction.md) for implementation details.

```python
# tests/unit/test_keyword_extraction.py

class TestKeywordExtractor:
    def test_extracts_colon_acronym(self):
        extractor = KeywordExtractor()
        keywords = extractor.extract(
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            abstract=None
        )
        assert "BERT" in keywords

    def test_extracts_parenthesis_acronym(self):
        extractor = KeywordExtractor()
        keywords = extractor.extract(
            title="Retrieval-Augmented Generation (RAG) for NLP",
            abstract=None
        )
        assert "RAG" in keywords

    def test_extracts_from_abstract(self):
        extractor = KeywordExtractor()
        keywords = extractor.extract(
            title="A New Approach",
            abstract="We introduce HyDE, a method that uses hypothetical documents."
        )
        assert "HyDE" in keywords

    def test_filters_stopwords(self):
        extractor = KeywordExtractor()
        keywords = extractor.extract(
            title="IT IS A METHOD",
            abstract=None
        )
        assert "IT" not in keywords
        assert "IS" not in keywords

    def test_minimum_length_filter(self):
        extractor = KeywordExtractor(min_keyword_length=2)
        keywords = extractor.extract(
            title="A B C Test Model",
            abstract=None
        )
        # Single letters should be filtered
        assert "A" not in keywords
        assert "B" not in keywords

    def test_keybert_extraction(self):
        extractor = KeywordExtractor(use_keybert=True, keybert_top_n=3)
        keywords = extractor.extract(
            title="Test Paper",
            abstract="This paper explores retrieval augmented generation for knowledge-intensive NLP tasks."
        )
        # KeyBERT should extract semantic keywords
        assert len(keywords) >= 1


class TestKeywordEnrichmentPipeline:
    async def test_batch_processing(self, storage_with_papers):
        pipeline = KeywordEnrichmentPipeline()
        stats = await pipeline.run(batch_size=10, limit=50)

        assert stats["processed_count"] == 50
        assert stats["papers_with_keywords"] > 0
```

### 3.5 Score Fusion Tests

```python
# tests/unit/test_score_fusion.py

class TestScoreFusion:
    def test_rrf_basic(self):
        fusion = ScoreFusion()
        bm25_results = [
            SearchHit(paper_id="p1", score=10.0),
            SearchHit(paper_id="p2", score=8.0),
            SearchHit(paper_id="p3", score=5.0),
        ]
        semantic_results = [
            SearchHit(paper_id="p2", score=0.95),
            SearchHit(paper_id="p1", score=0.90),
            SearchHit(paper_id="p4", score=0.85),
        ]

        result = fusion._reciprocal_rank_fusion(bm25_results, semantic_results)

        # p1 and p2 both rank high, so they get high RRF scores
        top_ids = [r.paper_id for r in result[:2]]
        assert "p1" in top_ids
        assert "p2" in top_ids

    def test_rrf_parameter_k(self):
        fusion = ScoreFusion()
        results = [SearchHit(paper_id="p1", score=1.0)]

        # When k=60, rank 1 score
        rrf_60 = fusion._reciprocal_rank_fusion(results, k=60)
        assert abs(rrf_60[0].score - 1/61) < 0.001

        # When k=0, rank 1 score
        rrf_0 = fusion._reciprocal_rank_fusion(results, k=0)
        assert abs(rrf_0[0].score - 1.0) < 0.001

    def test_weighted_fusion(self):
        fusion = ScoreFusion()
        bm25_results = [SearchHit(paper_id="p1", score=1.0)]
        semantic_results = [SearchHit(paper_id="p1", score=0.5)]

        result = fusion._weighted_fusion(
            bm25_results, semantic_results,
            bm25_weight=0.6, semantic_weight=0.4
        )

        # 0.6 * 1.0 + 0.4 * 0.5 = 0.8 (normalized)
        assert result[0].paper_id == "p1"

    def test_recency_boost(self):
        fusion = ScoreFusion()
        papers = [
            RankedPaper(paper_id="p1", score=1.0, year=2020),
            RankedPaper(paper_id="p2", score=1.0, year=2024),
        ]

        result = fusion._apply_recency_boost(papers, decay=0.1)

        # 2024 paper gets higher score
        assert result[0].paper_id == "p2"
```

---

## 4. Integration Tests

### 4.1 Search Pipeline Integration

```python
# tests/integration/test_search_pipeline.py

@pytest.mark.integration
class TestSearchPipeline:
    @pytest.fixture
    def pipeline(self, es_client, qdrant_client, db):
        return SearchPipeline(
            es_client=es_client,
            qdrant_client=qdrant_client,
            db=db
        )

    async def test_full_search_flow(self, pipeline):
        # Given: indexed test data
        await self._seed_test_data(pipeline)

        # When: execute search
        result = await pipeline.search(
            query="instruction tuning",
            options=SearchOptions(limit=10)
        )

        # Then: verify results
        assert result.total_count > 0
        assert len(result.papers) <= 10
        assert result.transparency.sources_searched

    async def test_hybrid_search_combines_results(self, pipeline):
        await self._seed_test_data(pipeline)

        result = await pipeline.search(
            query="Korean language model fine-tuning",
            options=SearchOptions(
                ranking="hybrid_rrf"
            )
        )

        # Both BM25 and semantic results are included
        assert any(p.scores.bm25 > 0 for p in result.papers)
        assert any(p.scores.semantic > 0 for p in result.papers)

    async def test_dedup_works_across_sources(self, pipeline):
        # Same paper collected from different sources
        paper = RawPaper(
            doi="10.1234/test",
            title="Test Paper",
            year=2023
        )
        await pipeline.index_from_openalex(paper)
        await pipeline.index_from_arxiv(paper)

        result = await pipeline.search(query="Test Paper")

        # Deduplicated to return only 1 result
        assert result.total_count == 1
        assert len(result.papers[0].source_matched) == 2


@pytest.mark.integration
class TestExternalAPIIntegration:
    @pytest.fixture
    def mock_openalex(self):
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.openalex.org/works",
                json={"results": [...], "meta": {"next_cursor": None}}
            )
            yield rsps

    async def test_openalex_search(self, mock_openalex):
        client = OpenAlexClient()
        results = await client.search("instruction tuning")

        assert len(results) > 0
        assert all(isinstance(r, RawPaper) for r in results)

    async def test_handles_api_rate_limit(self, mock_openalex):
        # Retry on 429 response
        mock_openalex.add(
            responses.GET,
            "https://api.openalex.org/works",
            status=429,
            headers={"Retry-After": "1"}
        )
        mock_openalex.add(
            responses.GET,
            "https://api.openalex.org/works",
            json={"results": [], "meta": {}}
        )

        client = OpenAlexClient()
        results = await client.search("test")

        # Success after retry
        assert results is not None
```

### 4.2 Database Integration

```python
# tests/integration/test_database.py

@pytest.mark.integration
class TestDatabaseOperations:
    @pytest.fixture
    def db(self, postgresql):
        return Database(postgresql)

    def test_paper_crud(self, db):
        paper = CanonicalPaper(
            title="Test Paper",
            year=2023,
            doi="10.1234/test"
        )

        # Create
        paper_id = db.create_paper(paper)
        assert paper_id is not None

        # Read
        fetched = db.get_paper(paper_id)
        assert fetched.title == "Test Paper"

        # Update
        db.update_paper(paper_id, citation_count=10)
        fetched = db.get_paper(paper_id)
        assert fetched.citation_count == 10

        # Delete
        db.delete_paper(paper_id)
        assert db.get_paper(paper_id) is None

    def test_dedup_finds_existing(self, db):
        # Find duplicates by DOI
        paper = CanonicalPaper(doi="10.1234/existing")
        db.create_paper(paper)

        existing = db.find_by_doi("10.1234/existing")
        assert existing is not None

    def test_version_linking(self, db):
        preprint = db.create_paper(CanonicalPaper(arxiv_id="2304.12345"))
        published = db.create_paper(CanonicalPaper(acl_id="2023.acl-main.1"))

        db.link_versions(preprint, published, "published_as")

        versions = db.get_versions(preprint)
        assert published in [v.related_paper_id for v in versions]
```

---

## 5. End-to-End Tests

### 5.1 API E2E Tests

```python
# tests/e2e/test_api.py

@pytest.mark.e2e
class TestSearchAPI:
    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_search_endpoint(self, client):
        response = client.post(
            "/v1/search",
            json={
                "query": "instruction tuning",
                "options": {"limit": 10}
            },
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "transparency" in data
        assert len(data["results"]) <= 10

    def test_search_with_filters(self, client):
        response = client.post(
            "/v1/search",
            json={
                "query": "Korean NLP",
                "options": {
                    "year_from": 2023,
                    "venues": ["ACL", "EMNLP"],
                    "paper_types": ["dataset"]
                }
            },
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 200
        data = response.json()

        for paper in data["results"]:
            assert paper["year"] >= 2023

    def test_export_bibtex(self, client):
        # First, search
        search_response = client.post(
            "/v1/search",
            json={"query": "test"},
            headers={"X-API-Key": "test-key"}
        )
        paper_ids = [p["id"] for p in search_response.json()["results"][:3]]

        # Export
        response = client.post(
            "/v1/export",
            json={
                "paper_ids": paper_ids,
                "format": "bibtex"
            },
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 200
        assert "@" in response.text  # BibTeX format

    def test_rate_limiting(self, client):
        # Rapid multiple requests
        for _ in range(15):
            client.post(
                "/v1/search",
                json={"query": "test"},
                headers={"X-API-Key": "test-key"}
            )

        response = client.post(
            "/v1/search",
            json={"query": "test"},
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 429


@pytest.mark.e2e
class TestMCPServer:
    @pytest.fixture
    def mcp_client(self, mcp_server):
        return MCPTestClient(mcp_server)

    async def test_search_papers_tool(self, mcp_client):
        result = await mcp_client.call_tool(
            "search_papers",
            {"query": "RAG evaluation", "limit": 5}
        )

        assert len(result["papers"]) <= 5
        assert all("title" in p for p in result["papers"])

    async def test_get_paper_details_tool(self, mcp_client):
        # Search then get details
        search = await mcp_client.call_tool(
            "search_papers",
            {"query": "test", "limit": 1}
        )
        paper_id = search["papers"][0]["id"]

        result = await mcp_client.call_tool(
            "get_paper_details",
            {"paper_id": paper_id}
        )

        assert result["id"] == paper_id
        assert "abstract" in result
```

---

## 6. Performance Tests

### 6.1 Load Testing

```python
# tests/performance/test_load.py

@pytest.mark.performance
class TestSearchPerformance:
    def test_search_latency_p95(self, benchmark):
        """Search P95 latency < 2 seconds"""
        client = SearchClient()

        results = benchmark.pedantic(
            client.search,
            args=("instruction tuning",),
            iterations=100,
            rounds=3
        )

        assert benchmark.stats["mean"] < 2.0
        assert benchmark.stats["p95"] < 3.0

    def test_concurrent_searches(self):
        """Handle 100 concurrent searches"""
        client = SearchClient()

        async def run_concurrent():
            tasks = [
                client.search(f"query {i}")
                for i in range(100)
            ]
            results = await asyncio.gather(*tasks)
            return results

        start = time.time()
        results = asyncio.run(run_concurrent())
        elapsed = time.time() - start

        assert len(results) == 100
        assert elapsed < 30  # Within 30 seconds


@pytest.mark.performance
class TestIndexPerformance:
    def test_bulk_indexing_throughput(self):
        """Index 1000 papers per second"""
        indexer = PaperIndexer()
        papers = generate_test_papers(10000)

        start = time.time()
        indexer.bulk_index(papers)
        elapsed = time.time() - start

        throughput = len(papers) / elapsed
        assert throughput >= 1000
```

### 6.2 Stress Testing

```yaml
# k6/stress-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m', target: 50 },   // Ramp up
    { duration: '5m', target: 50 },   // Stay
    { duration: '2m', target: 100 },  // Ramp up more
    { duration: '5m', target: 100 },  // Stay
    { duration: '2m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const payload = JSON.stringify({
    query: `query_${__VU}_${__ITER}`,
    options: { limit: 50 }
  });

  const res = http.post(
    'https://api.lexiconarxiv.io/v1/search',
    payload,
    { headers: { 'Content-Type': 'application/json', 'X-API-Key': 'test' } }
  );

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has results': (r) => JSON.parse(r.body).results.length > 0,
  });

  sleep(1);
}
```

---

## 7. Search Quality Tests

### 7.1 Recall Evaluation

```python
# tests/quality/test_recall.py

class TestSearchRecall:
    """Measure recall for known relevant papers"""

    @pytest.fixture
    def ground_truth(self):
        """Manually labeled test set"""
        return {
            "instruction tuning": [
                "2304.12345",  # KULLM
                "2303.18223",  # Alpaca
                "2302.13971",  # LLaMA
                # ... more known relevant papers
            ],
            "RAG evaluation": [
                "2309.01431",  # RAGAS
                "2310.01065",  # ARES
                # ...
            ]
        }

    def test_recall_at_100(self, search_client, ground_truth):
        """Measure recall in top 100 results"""
        for query, relevant_ids in ground_truth.items():
            results = search_client.search(query, limit=100)
            result_ids = {p.arxiv_id for p in results.papers}

            hits = len(result_ids.intersection(relevant_ids))
            recall = hits / len(relevant_ids)

            assert recall >= 0.7, f"Recall for '{query}': {recall}"

    def test_recall_vs_google_scholar(self, search_client):
        """Compare recall against Google Scholar"""
        # Compare with pre-collected Scholar results
        scholar_results = load_scholar_baseline()

        for query, scholar_papers in scholar_results.items():
            our_results = search_client.search(query, limit=500)
            our_ids = {p.doi or p.title for p in our_results.papers}
            scholar_ids = {p.doi or p.title for p in scholar_papers}

            overlap = len(our_ids.intersection(scholar_ids))
            our_unique = len(our_ids - scholar_ids)

            # Minimum 80% overlap
            assert overlap / len(scholar_ids) >= 0.8
            # Additional papers found
            assert our_unique > 0
```

### 7.2 Ranking Quality

```python
# tests/quality/test_ranking.py

class TestRankingQuality:
    def test_ndcg_at_10(self, search_client, relevance_judgments):
        """Measure NDCG@10"""
        for query, judgments in relevance_judgments.items():
            results = search_client.search(query, limit=10)

            dcg = 0
            for i, paper in enumerate(results.papers, 1):
                rel = judgments.get(paper.id, 0)
                dcg += rel / math.log2(i + 1)

            # Ideal DCG
            ideal_rels = sorted(judgments.values(), reverse=True)[:10]
            idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels))

            ndcg = dcg / idcg if idcg > 0 else 0
            assert ndcg >= 0.6

    def test_relevant_in_top_5(self, search_client, known_relevant):
        """Known relevant papers should be in top 5"""
        for query, must_include in known_relevant.items():
            results = search_client.search(query, limit=5)
            top_ids = {p.id for p in results.papers}

            for paper_id in must_include:
                assert paper_id in top_ids, f"{paper_id} not in top 5 for '{query}'"
```

---

## 8. CI/CD Integration

### 8.1 GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements-test.txt
      - run: pytest tests/unit -v --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v4

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
      elasticsearch:
        image: elasticsearch:8.11.0
      qdrant:
        image: qdrant/qdrant
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/integration -v -m integration

  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    steps:
      - uses: actions/checkout@v4
      - run: docker-compose up -d
      - run: pytest tests/e2e -v -m e2e
      - run: docker-compose down

  performance-tests:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/performance -v -m performance
```

---

## 9. Test Data Management

### 9.1 Fixtures

```python
# tests/conftest.py

@pytest.fixture
def sample_papers():
    return [
        RawPaper(
            title="KULLM: Korean Large Language Model",
            arxiv_id="2304.12345",
            year=2023,
            authors=[{"name": "Kim"}],
            abstract="We present KULLM..."
        ),
        RawPaper(
            title="Alpaca: A Strong Open-Source LLM",
            arxiv_id="2303.18223",
            year=2023,
            authors=[{"name": "Taori"}],
            abstract="We present Alpaca..."
        ),
        # ...
    ]

@pytest.fixture
def seeded_database(db, sample_papers):
    for paper in sample_papers:
        db.create_paper(paper)
    yield db
    db.clear()
```

### 9.2 New Test Areas

The following areas have been added or are planned for expanded coverage:

**Advanced Retrieval Pipeline Tests**
- HyDE (Hypothetical Document Embeddings): verify that LLM-generated hypothetical abstracts improve recall on vague queries.
- Cross-encoder reranker: validate that reranking top-50 results with Qwen3-Reranker-0.6B improves nDCG@10.
- MMR (Maximal Marginal Relevance): confirm that diversity post-processing reduces redundancy without dropping relevant results.

**Section-level Embedding Quality**
- Verify that section-level vectors (method, task, result, etc.) cluster by semantic type.
- Regression tests for section extraction: ensure structured-abstract parsing does not degrade across model updates.

**Incremental Pipeline End-to-End Testing**
- Simulate incremental collection, embedding, similarity recomputation, and clustering on a small fixture corpus.
- Verify that partially embedded papers are recovered correctly after interruption.

### 9.3 Test Data Generation

```python
# tests/utils/generators.py

def generate_test_papers(n: int) -> List[RawPaper]:
    fake = Faker()
    papers = []

    for i in range(n):
        papers.append(RawPaper(
            title=fake.sentence(nb_words=8),
            abstract=fake.paragraph(nb_sentences=5),
            year=fake.random_int(min=2018, max=2024),
            authors=[{"name": fake.name()} for _ in range(3)],
            arxiv_id=f"2304.{fake.random_int(min=10000, max=99999)}",
            source="test"
        ))

    return papers
```
