# Testing Strategy

## 1. Overview

본 문서는 AI/NLP 논문 검색 엔진의 테스트 전략과 품질 보증 방법을 정의합니다.

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
        result = analyzer.analyze("한국어 LLM 논문")

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

### 3.4 Score Fusion Tests

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

        # p1과 p2가 둘 다 상위에 있으므로 높은 RRF 점수
        top_ids = [r.paper_id for r in result[:2]]
        assert "p1" in top_ids
        assert "p2" in top_ids

    def test_rrf_parameter_k(self):
        fusion = ScoreFusion()
        results = [SearchHit(paper_id="p1", score=1.0)]

        # k=60일 때 rank 1의 점수
        rrf_60 = fusion._reciprocal_rank_fusion(results, k=60)
        assert abs(rrf_60[0].score - 1/61) < 0.001

        # k=0일 때 rank 1의 점수
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

        # 2024 논문이 더 높은 점수
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
        # Given: 인덱싱된 테스트 데이터
        await self._seed_test_data(pipeline)

        # When: 검색 실행
        result = await pipeline.search(
            query="instruction tuning",
            options=SearchOptions(limit=10)
        )

        # Then: 결과 검증
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

        # BM25와 semantic 결과가 모두 포함
        assert any(p.scores.bm25 > 0 for p in result.papers)
        assert any(p.scores.semantic > 0 for p in result.papers)

    async def test_dedup_works_across_sources(self, pipeline):
        # 동일 논문이 다른 소스에서 수집된 경우
        paper = RawPaper(
            doi="10.1234/test",
            title="Test Paper",
            year=2023
        )
        await pipeline.index_from_openalex(paper)
        await pipeline.index_from_arxiv(paper)

        result = await pipeline.search(query="Test Paper")

        # 중복 제거되어 1개만 반환
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
        # 429 응답 시 재시도
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

        # 재시도 후 성공
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
        # DOI로 중복 찾기
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
        # 먼저 검색
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
        # 빠르게 여러 요청
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
        # 검색 후 상세 조회
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
        """검색 P95 latency < 2초"""
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
        """동시 검색 100건 처리"""
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
        assert elapsed < 30  # 30초 이내


@pytest.mark.performance
class TestIndexPerformance:
    def test_bulk_indexing_throughput(self):
        """초당 1000 논문 인덱싱"""
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
    """Known relevant papers에 대한 recall 측정"""

    @pytest.fixture
    def ground_truth(self):
        """수동으로 레이블링된 테스트 셋"""
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
        """Top 100 결과에서 recall 측정"""
        for query, relevant_ids in ground_truth.items():
            results = search_client.search(query, limit=100)
            result_ids = {p.arxiv_id for p in results.papers}

            hits = len(result_ids.intersection(relevant_ids))
            recall = hits / len(relevant_ids)

            assert recall >= 0.7, f"Recall for '{query}': {recall}"

    def test_recall_vs_google_scholar(self, search_client):
        """Google Scholar 대비 recall 비교"""
        # 사전에 수집된 Scholar 결과와 비교
        scholar_results = load_scholar_baseline()

        for query, scholar_papers in scholar_results.items():
            our_results = search_client.search(query, limit=500)
            our_ids = {p.doi or p.title for p in our_results.papers}
            scholar_ids = {p.doi or p.title for p in scholar_papers}

            overlap = len(our_ids.intersection(scholar_ids))
            our_unique = len(our_ids - scholar_ids)

            # 최소 80% overlap
            assert overlap / len(scholar_ids) >= 0.8
            # 추가 발견 논문 존재
            assert our_unique > 0
```

### 7.2 Ranking Quality

```python
# tests/quality/test_ranking.py

class TestRankingQuality:
    def test_ndcg_at_10(self, search_client, relevance_judgments):
        """NDCG@10 측정"""
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
        """알려진 관련 논문이 top 5에 포함"""
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

### 9.2 Test Data Generation

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
