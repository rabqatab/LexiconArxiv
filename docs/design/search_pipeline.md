# Search Pipeline Design

## 1. Overview

본 문서는 **Core-first 하이브리드 검색 파이프라인**의 상세 설계를 정의합니다.

### 1.1 Key Principles

- **Core-first**: Top-tier venue 논문을 우선 검색하고 가중치 부여
- **On-demand Extension**: 필요 시 arXiv/OpenAlex로 확장 검색
- **Connection-aware**: On-demand 논문의 Core 연결 관계 표시
- **Transparent**: 검색 범위와 누락 가능성 명시

---

## 2. Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Core-first Search Pipeline                       │
│                                                                     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐         │
│  │  Query  │───▶│ Query   │───▶│ Search  │───▶│ Result  │───▶ Out │
│  │  Input  │    │ Planner │    │ Executor│    │ Processor│         │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘         │
│                      │              │                               │
│                      │         ┌────┴────┐                          │
│                      │         │         │                          │
│                      ▼         ▼         ▼                          │
│                 ┌─────────┐ ┌─────────┐ ┌─────────┐                │
│                 │  Core   │ │On-demand│ │Connection│                │
│                 │ Search  │ │ Search  │ │Detector │                │
│                 └─────────┘ └─────────┘ └─────────┘                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Stage 1: Query Planner

### 3.1 Query Analysis

```python
@dataclass
class QueryAnalysis:
    original_query: str
    language: str                    # en, ko
    detected_entities: List[Entity]
    query_type: QueryType            # discovery, monitoring, specific
    target_field: str                # NLP, ML, AI, IR, DM, Web, ALL
    complexity: float                # 0-1

@dataclass
class Entity:
    text: str
    type: EntityType  # YEAR, VENUE, TOPIC, AUTHOR, PAPER_TYPE, FIELD
    confidence: float
    normalized: str
```

**Entity Extraction Examples**:

| Input | Extracted Entities |
|-------|-------------------|
| "RAG papers from 2024" | TOPIC: "RAG", YEAR: 2024, FIELD: NLP |
| "ACL 2023 summarization" | VENUE: "ACL", YEAR: 2023, TOPIC: "summarization" |
| "recent LLM benchmarks" | TOPIC: "LLM benchmark", FIELD: NLP, TYPE: benchmark |

### 3.2 Search Strategy Selection

```python
class SearchStrategySelector:
    def select(self, analysis: QueryAnalysis) -> SearchStrategy:
        # Core-first strategy (default)
        base = SearchStrategy(
            search_core=True,
            search_ondemand=True,
            core_boost=2.0,  # Core 논문 점수 2배
            fusion_method="rrf"
        )

        # Discovery query: Core + On-demand 모두 활용
        if analysis.query_type == QueryType.DISCOVERY:
            return base.with_updates(
                ondemand_sources=["arxiv", "openalex"],
                max_core_results=200,
                max_ondemand_results=100
            )

        # Monitoring query: 최신 arXiv 강조
        elif analysis.query_type == QueryType.MONITORING:
            return base.with_updates(
                ondemand_sources=["arxiv"],
                recency_boost=True,
                recency_decay=0.1,
                max_ondemand_results=50
            )

        # Specific query: Core only (precision)
        else:
            return base.with_updates(
                search_ondemand=False,
                max_core_results=100
            )
```

---

## 4. Stage 2: Search Executor

### 4.1 Core Corpus Search (Primary)

```python
class CoreSearchExecutor:
    """Core Corpus 내 검색 (Qdrant hybrid)"""

    async def search(self, query: ExpandedQuery, strategy: SearchStrategy) -> List[CoreHit]:
        # 1. Hybrid search (vector + BM25)
        results = await self.qdrant.search(
            collection_name="paper_embeddings",
            query_vector=self.encode(query.primary),
            query_text=query.primary,  # BM25용
            limit=strategy.max_core_results,
            query_filter=self._build_core_filter(query),
            search_params=SearchParams(
                hnsw_ef=128,
                exact=False
            )
        )

        return [
            CoreHit(
                paper_id=r.id,
                score=r.score,
                tier=r.payload["tier"],
                venue=r.payload["venue"],
                is_core=True
            )
            for r in results
        ]

    def _build_core_filter(self, query: ExpandedQuery) -> Filter:
        conditions = [
            FieldCondition(key="is_core", match=MatchValue(value=True))
        ]

        if query.year_filter:
            conditions.append(FieldCondition(
                key="year",
                range=Range(gte=query.year_filter.from_year, lte=query.year_filter.to_year)
            ))

        if query.field_filter:
            conditions.append(FieldCondition(
                key="field",
                match=MatchValue(value=query.field_filter)
            ))

        if query.tier_filter is not None:
            conditions.append(FieldCondition(
                key="tier",
                match=MatchValue(value=query.tier_filter)
            ))

        return Filter(must=conditions)
```

### 4.2 On-demand Search (Extension)

```python
class OnDemandSearchExecutor:
    """On-demand 검색 (arXiv, OpenAlex)"""

    async def search(
        self,
        query: ExpandedQuery,
        strategy: SearchStrategy
    ) -> List[OnDemandHit]:

        tasks = []
        if "arxiv" in strategy.ondemand_sources:
            tasks.append(self._search_arxiv(query))
        if "openalex" in strategy.ondemand_sources:
            tasks.append(self._search_openalex(query))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and filter errors
        papers = []
        for result in results:
            if isinstance(result, list):
                papers.extend(result)

        # Detect Core connections
        for paper in papers:
            paper.core_connections = await self._detect_connections(paper)

        return papers

    async def _search_arxiv(self, query: ExpandedQuery) -> List[OnDemandHit]:
        """arXiv API 검색 (cs.CL, cs.AI, cs.LG, cs.IR only)"""
        papers = await self.arxiv_client.search(
            query=query.primary,
            categories=["cs.CL", "cs.AI", "cs.LG", "cs.IR"],  # Vision, Robotics 제외
            max_results=100
        )

        return [
            OnDemandHit(
                paper_id=p.arxiv_id,
                source="arxiv",
                title=p.title,
                year=p.year,
                is_core=False,
                core_connections=[]  # 후에 채움
            )
            for p in papers
        ]

    async def _search_openalex(self, query: ExpandedQuery) -> List[OnDemandHit]:
        """OpenAlex narrow query"""
        papers = await self.openalex_client.search(
            query=query.primary,
            filter="type:article|preprint",
            per_page=100
        )

        return [
            OnDemandHit(
                paper_id=p.openalex_id,
                source="openalex",
                title=p.title,
                year=p.year,
                is_core=False,
                core_connections=[]
            )
            for p in papers
        ]
```

### 4.3 Core Connection Detection

```python
class CoreConnectionDetector:
    """On-demand 논문의 Core 연결 관계 탐지"""

    async def detect(self, paper: OnDemandHit) -> List[CoreConnection]:
        connections = []

        # 1. DOI 매칭 (프리프린트 → 출판본)
        if paper.doi:
            core_match = await self.db.find_core_by_doi(paper.doi)
            if core_match:
                connections.append(CoreConnection(
                    type="published_as",
                    core_paper_id=core_match.id,
                    confidence=1.0
                ))

        # 2. 인용 관계 탐지
        if paper.referenced_works:
            for ref_id in paper.referenced_works:
                if await self.db.is_core(ref_id):
                    connections.append(CoreConnection(
                        type="cites_core",
                        core_paper_id=ref_id,
                        confidence=1.0
                    ))

        # 3. Semantic similarity (threshold: 0.85)
        if paper.embedding:
            similar_core = await self.qdrant.search(
                collection_name="paper_embeddings",
                query_vector=paper.embedding,
                limit=5,
                query_filter=Filter(must=[
                    FieldCondition(key="is_core", match=MatchValue(value=True))
                ]),
                score_threshold=0.85
            )
            for hit in similar_core:
                connections.append(CoreConnection(
                    type="similar_to",
                    core_paper_id=hit.id,
                    confidence=hit.score
                ))

        return connections
```

---

## 5. Stage 3: Result Processor

### 5.1 Score Fusion with Core Boost

```python
class CoreFirstScoreFusion:
    """Core-first 점수 융합"""

    def fuse(
        self,
        core_results: List[CoreHit],
        ondemand_results: List[OnDemandHit],
        strategy: SearchStrategy
    ) -> List[RankedPaper]:

        # 1. RRF 기반 기본 점수 계산
        all_results = core_results + ondemand_results
        rrf_scores = self._reciprocal_rank_fusion(all_results)

        # 2. Core boost 적용
        for paper in rrf_scores:
            if paper.is_core:
                paper.score *= strategy.core_boost  # 기본 2.0배

            # Tier 0은 추가 boost
            if paper.tier == 0:
                paper.score *= 1.2

        # 3. Recency boost (옵션)
        if strategy.recency_boost:
            rrf_scores = self._apply_recency_boost(rrf_scores, strategy.recency_decay)

        # 4. Connection count boost for on-demand
        for paper in rrf_scores:
            if not paper.is_core and paper.core_connections:
                # Core 연결이 많을수록 점수 상승
                connection_boost = 1 + 0.1 * len(paper.core_connections)
                paper.score *= connection_boost

        # 5. 최종 정렬
        return sorted(rrf_scores, key=lambda x: x.score, reverse=True)

    def _reciprocal_rank_fusion(
        self,
        *result_lists: List[SearchHit],
        k: int = 60
    ) -> List[RankedPaper]:
        """RRF Score = Σ 1 / (k + rank_i)"""
        scores = defaultdict(float)
        paper_data = {}

        for results in result_lists:
            for rank, hit in enumerate(results, 1):
                scores[hit.paper_id] += 1.0 / (k + rank)
                paper_data[hit.paper_id] = hit

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return [
            RankedPaper(
                paper_id=pid,
                score=score,
                is_core=paper_data[pid].is_core,
                tier=paper_data[pid].tier,
                core_connections=paper_data[pid].core_connections,
                rank=i+1
            )
            for i, (pid, score) in enumerate(ranked)
        ]
```

### 5.2 Deduplication

```python
class Deduplicator:
    def dedupe(self, papers: List[RawPaper]) -> List[CanonicalPaper]:
        # Phase 1: DOI/arXiv ID exact matching
        by_doi = defaultdict(list)
        by_arxiv = defaultdict(list)

        for paper in papers:
            if paper.doi:
                by_doi[paper.doi].append(paper)
            if paper.arxiv_id:
                by_arxiv[paper.arxiv_id].append(paper)

        # Phase 2: Fuzzy title matching
        unmatched = [p for p in papers if not self._is_matched(p)]
        fuzzy_groups = self._fuzzy_match_titles(unmatched)

        # Phase 3: Merge - Core 버전 우선
        canonical = []
        for group in self._all_groups(by_doi, by_arxiv, fuzzy_groups):
            canonical.append(self._merge_prefer_core(group))

        return canonical

    def _merge_prefer_core(self, group: List[RawPaper]) -> CanonicalPaper:
        """Core 버전을 primary로 선택"""
        # Core 논문 우선
        core_papers = [p for p in group if p.is_core]
        if core_papers:
            primary = core_papers[0]
        else:
            # 가장 완전한 메타데이터를 가진 것 선택
            primary = max(group, key=lambda p: self._completeness_score(p))

        return CanonicalPaper(
            primary=primary,
            versions=[p for p in group if p != primary],
            is_core=any(p.is_core for p in group)
        )
```

---

## 6. Graph-based Search Extension

### 6.1 Citation Network Traversal

```python
class GraphSearchExtension:
    """인용 그래프 기반 검색 확장"""

    async def expand_by_citations(
        self,
        seed_papers: List[str],
        depth: int = 1,
        direction: str = "both"  # "references", "citations", "both"
    ) -> List[RelatedPaper]:
        """
        seed_papers를 기반으로 인용 그래프 탐색

        Args:
            seed_papers: 시작 논문 ID 리스트
            depth: 탐색 깊이 (1 = 직접 인용만)
            direction: 탐색 방향
        """
        visited = set(seed_papers)
        related = []

        current_level = seed_papers
        for d in range(depth):
            next_level = []

            for paper_id in current_level:
                # 이 논문이 인용한 Core 논문들
                if direction in ("references", "both"):
                    refs = await self.db.get_references(paper_id, core_only=True)
                    for ref in refs:
                        if ref.id not in visited:
                            visited.add(ref.id)
                            next_level.append(ref.id)
                            related.append(RelatedPaper(
                                paper_id=ref.id,
                                relation="referenced_by",
                                source_paper=paper_id,
                                depth=d+1
                            ))

                # 이 논문을 인용한 Core 논문들
                if direction in ("citations", "both"):
                    cites = await self.db.get_citations(paper_id, core_only=True)
                    for cite in cites:
                        if cite.id not in visited:
                            visited.add(cite.id)
                            next_level.append(cite.id)
                            related.append(RelatedPaper(
                                paper_id=cite.id,
                                relation="cites",
                                source_paper=paper_id,
                                depth=d+1
                            ))

            current_level = next_level

        return related
```

### 6.2 Similar Paper Discovery

```python
class SimilarPaperFinder:
    """유사 논문 탐색 (Core 내)"""

    async def find_similar(
        self,
        paper_id: str,
        limit: int = 20,
        core_only: bool = True
    ) -> List[SimilarPaper]:
        """특정 논문과 유사한 Core 논문 탐색"""

        # 1. 해당 논문의 embedding 조회
        paper = await self.db.get_paper(paper_id)
        if not paper or not paper.embedding:
            return []

        # 2. Vector similarity search
        filter_conditions = []
        if core_only:
            filter_conditions.append(
                FieldCondition(key="is_core", match=MatchValue(value=True))
            )

        results = await self.qdrant.search(
            collection_name="paper_embeddings",
            query_vector=paper.embedding,
            limit=limit + 1,  # 자기 자신 제외용
            query_filter=Filter(must=filter_conditions) if filter_conditions else None
        )

        return [
            SimilarPaper(
                paper_id=r.id,
                similarity=r.score,
                shared_citations=await self._count_shared_citations(paper_id, r.id)
            )
            for r in results
            if r.id != paper_id
        ][:limit]
```

---

## 7. Transparency Metadata

```python
@dataclass
class TransparencyInfo:
    sources_searched: List[str]
    raw_counts: Dict[str, int]
    after_dedup: int
    core_count: int
    ondemand_count: int
    connected_ondemand: int  # Core 연결이 있는 on-demand 수
    search_strategy: str
    execution_time_ms: int
    coverage_notes: List[str]
    potential_gaps: List[str]

class TransparencyGenerator:
    def generate(
        self,
        core_results: List[CoreHit],
        ondemand_results: List[OnDemandHit],
        final_results: List[RankedPaper]
    ) -> TransparencyInfo:

        connected = [p for p in ondemand_results if p.core_connections]

        return TransparencyInfo(
            sources_searched=["Core Corpus (Tier 0+1)", "arXiv", "OpenAlex"],
            raw_counts={
                "Core": len(core_results),
                "arXiv": len([p for p in ondemand_results if p.source == "arxiv"]),
                "OpenAlex": len([p for p in ondemand_results if p.source == "openalex"])
            },
            after_dedup=len(final_results),
            core_count=len([p for p in final_results if p.is_core]),
            ondemand_count=len([p for p in final_results if not p.is_core]),
            connected_ondemand=len(connected),
            search_strategy="Core-first hybrid",
            coverage_notes=[
                f"Core Corpus: {len(core_results)}개 (Tier 0/1 venue)",
                f"On-demand: {len(ondemand_results)}개 (arXiv + OpenAlex)",
                f"Core 연결된 On-demand: {len(connected)}개"
            ],
            potential_gaps=[
                "Google Scholar는 포함되지 않음",
                "Vision/Robotics/Speech venue는 제외됨",
                "Core 연결 없는 최신 arXiv는 하위 랭킹"
            ]
        )
```

---

## 8. Performance Optimization

### 8.1 Caching Strategy

```python
class SearchCache:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.core_ttl = 3600      # Core 결과: 1시간
        self.ondemand_ttl = 300   # On-demand: 5분

    async def get_or_compute(
        self,
        query: ExpandedQuery,
        compute_fn: Callable
    ) -> SearchResult:
        # Core 결과 캐시 확인
        core_key = f"core:{query.hash()}"
        cached_core = await self.redis.get(core_key)

        if cached_core:
            core_results = deserialize(cached_core)
        else:
            core_results = await compute_fn.core_search(query)
            await self.redis.setex(core_key, self.core_ttl, serialize(core_results))

        # On-demand는 별도 캐시 (더 짧은 TTL)
        ondemand_key = f"ondemand:{query.hash()}"
        # ...

        return SearchResult(core=core_results, ondemand=ondemand_results)
```

### 8.2 Index Optimization

- **Qdrant**:
  - Core 컬렉션: m=16, ef_construct=128
  - Payload indexing: tier, field, year, is_core
  - Quantization: scalar (메모리 50% 절약)

### 8.3 Query Timeout

```python
TIMEOUTS = {
    "core_search": 3.0,      # 3초
    "arxiv": 10.0,           # 10초
    "openalex": 8.0,         # 8초
    "connection_detect": 2.0  # 2초
}

async def search_with_fallback(tasks, timeout):
    """일부 실패해도 Core 결과는 항상 반환"""
    done, pending = await asyncio.wait(tasks, timeout=timeout)

    for task in pending:
        task.cancel()

    # Core 결과가 있으면 항상 반환
    results = [t.result() for t in done if not t.exception()]
    return results
```

---

## 9. Search Modes Summary

| Mode | Core Search | On-demand | Core Boost | Use Case |
|------|-------------|-----------|------------|----------|
| **Core-only** | ✓ | ✗ | 1.0 | Precision, verified results |
| **Core-first** | ✓ | ✓ | 2.0 | Default, balanced |
| **Balanced** | ✓ | ✓ | 1.0 | Discovery, maximum recall |
| **Monitoring** | ✓ | ✓ (arXiv only) | 1.5 + recency | Latest papers tracking |
