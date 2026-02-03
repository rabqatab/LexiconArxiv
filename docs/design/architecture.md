# Technical Architecture Document

## 1. System Overview

본 문서는 AI 연구 인사이트 엔진의 기술 아키텍처를 정의합니다.

### 1.1 Architecture Principles

- **Core-first**: Top-tier venue 논문을 기준점(anchor)으로 활용
- **On-demand Extension**: 질의 시점에 최신 논문 확장 검색
- **Graph-aware**: 인용 그래프 기반 연결 관계 탐색
- **Graceful Degradation**: 외부 API 장애 시에도 Core Corpus 기반 검색 유지
- **Observability First**: 모든 파이프라인에 메트릭/로깅 내장

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Layer                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │   Web    │  │   CLI    │  │   API    │  │   MCP Server     │    │
│  │   App    │  │  Client  │  │  Client  │  │   (Agent용)      │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘    │
└───────┼─────────────┼─────────────┼─────────────────┼──────────────┘
        │             │             │                 │
        └─────────────┴──────┬──────┴─────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────────────┐
│                      API Gateway                                    │
│  ┌─────────────────────────┴──────────────────────────────────┐    │
│  │  Rate Limiting │ Auth │ Request Routing │ Response Cache   │    │
│  └────────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────────────┐
│                     Application Layer                               │
│                                                                     │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐    │
│  │  Query Service │  │  Search Service│  │   Graph Service    │    │
│  │  - NL parsing  │  │  - Hybrid rank │  │  - Citation graph  │    │
│  │  - Intent      │  │  - Core-first  │  │  - Trend analysis  │    │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────────┘    │
│          │                   │                   │                  │
│  ┌───────┴───────────────────┴───────────────────┴─────────────┐   │
│  │                    Search Orchestrator                       │   │
│  │  - Core Corpus search (primary)                              │   │
│  │  - On-demand retrieval (extension)                           │   │
│  │  - Core connection detection                                 │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
└────────────────────────────┼────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────┴────────┐  ┌────────┴───────┐  ┌────────┴───────┐
│  Core Corpus   │  │  On-demand     │  │  Data Pipeline │
│  Layer         │  │  Layer         │  │  Layer         │
│                │  │                │  │                │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
│ │ PostgreSQL │ │  │ │   arXiv    │ │  │ │  Core      │ │
│ │(Core meta) │ │  │ │    API     │ │  │ │ Collector  │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
│ │  Qdrant    │ │  │ │  OpenAlex  │ │  │ │  Citation  │ │
│ │(Core+BM25) │ │  │ │  (narrow)  │ │  │ │  Graph     │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
│ ┌────────────┐ │  │                │  │ ┌────────────┐ │
│ │ Citation   │ │  │                │  │ │  Embedding │ │
│ │  Graph     │ │  │                │  │ │  Pipeline  │ │
│ └────────────┘ │  │                │  │ └────────────┘ │
└────────────────┘  └────────────────┘  └────────────────┘
```

---

## 3. Core vs On-demand Architecture

### 3.1 Core Corpus Layer

**사전 수집된 Top-tier venue 논문** (Tier 0 + Tier 1 + Tier 2)

```
┌─────────────────────────────────────────────────────────────┐
│                     Core Corpus                              │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Tier 0      │    │ Tier 1      │    │ Tier 2      │     │
│  │ (11 venues) │───▶│ (13 venues) │───▶│ (3 venues)  │     │
│  │ ML/AI/NLP   │    │ Extended    │    │ Legal AI    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                  │                  │             │
│         └──────────────────┴──────────────────┘             │
│                            │                                 │
│                     ┌──────┴──────┐                         │
│                     │  Citation   │                         │
│                     │   Graph     │                         │
│                     └─────────────┘                         │
│                                                              │
│  Data Sources:                                               │
│  - OpenAlex: ML/AI venues (~40K papers)                     │
│  - ACL Anthology: NLP venues (~20K papers)                  │
│  - DBLP: IR/Legal venues (~5K papers)                       │
│                                                              │
│  Storage:                                                    │
│  - PostgreSQL: 메타데이터, 인용 관계                          │
│  - Qdrant: Embedding + BM25 hybrid index                    │
│  - ~65K papers (2020-2024)                                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 On-demand Retrieval Layer

**질의 시점에 확장 검색**

```
┌─────────────────────────────────────────────────────────────┐
│                   On-demand Retrieval                        │
├─────────────────────────────────────────────────────────────┤
│  User Query                                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Core Search │───▶│ arXiv API   │───▶│ Connection  │     │
│  │ (primary)   │    │ (extension) │    │ Detection   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                              │
│  Connection Types:                                           │
│  - cites_core: arXiv 논문이 Core 인용                        │
│  - cited_by_core: Core가 arXiv 인용                          │
│  - published_as: 프리프린트 → Core 출판본                     │
│  - similar_to: Semantic 유사도                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Component Details

### 4.1 Query Service

**책임**: 사용자 자연어 질의를 검색 가능한 구조로 변환

```python
class QueryService:
    def process(self, natural_query: str) -> SearchIntent:
        # 1. Language detection
        # 2. Entity extraction (venues, years, topics)
        # 3. Query expansion (synonyms, related terms)
        # 4. Search strategy selection (Core-first or balanced)
        pass
```

**주요 기능**:
- 자연어 파싱 (한국어/영어 지원)
- 연도/venue/field 추출
- 쿼리 확장 (동의어, 관련 용어)
- 검색 전략 결정 (Core-only, Core-first, Balanced)

### 4.2 Search Orchestrator

**책임**: Core + On-demand 검색 조율 및 결과 통합

```python
class SearchOrchestrator:
    async def search(self, intent: SearchIntent) -> SearchResult:
        # 1. Core Corpus 검색 (primary)
        core_results = await self.core_index.search(intent)

        # 2. On-demand 확장 (필요 시)
        if intent.include_ondemand:
            ondemand_results = await asyncio.gather(
                self.arxiv_client.search(intent),
                self.openalex_client.narrow_search(intent),
            )

            # 3. Core 연결 탐지
            for paper in ondemand_results:
                paper.core_connections = await self.detect_connections(paper)

        # 4. 결과 통합 및 랭킹
        merged = self.merger.merge(core_results, ondemand_results)
        ranked = self.ranker.rank(merged, intent.ranking_strategy)

        # 5. Core-first 가중치 적용
        ranked = self.apply_core_boost(ranked)

        return SearchResult(papers=ranked, core_count=len(core_results))
```

### 4.3 Graph Service (NEW)

**책임**: 인용 그래프 탐색 및 트렌드 분석

```python
class GraphService:
    async def get_citation_network(self, paper_id: str, depth: int = 2) -> CitationGraph:
        """특정 논문의 인용 네트워크 반환"""
        # 1. 해당 논문이 인용한 Core 논문들
        references = await self.db.get_references(paper_id, core_only=True)

        # 2. 해당 논문을 인용한 논문들
        citations = await self.db.get_citations(paper_id, core_only=True)

        # 3. 그래프 구축
        return CitationGraph(
            center=paper_id,
            references=references,
            citations=citations,
            depth=depth
        )

    async def get_field_trends(self, field: str, years: int = 5) -> TrendAnalysis:
        """분야별 트렌드 분석"""
        # 1. 연도별 논문 수
        # 2. 주요 키워드 변화
        # 3. Notable 논문 선정 (높은 인용, 최근 급상승)
        pass

    async def find_notable_papers(self, field: str, limit: int = 20) -> List[Paper]:
        """Notable 논문 자동 선정"""
        # 기준: 인용 수, venue tier, 최신성, citation velocity
        pass
```

### 4.4 Core Corpus Layer

#### PostgreSQL (Metadata + Graph Store)
- Core paper records (tier 0/1)
- Citation edges (referenced_works)
- Core connections for on-demand papers
- Authors and venues

#### Qdrant (Hybrid Index)
- Vector search (768-dim embeddings)
- BM25 keyword search
- Payload filtering (tier, field, year)
- Core-first boosting

### 4.5 On-demand Retrieval

```python
class OnDemandRetriever:
    async def search_arxiv(self, query: str) -> List[Paper]:
        """arXiv 최신 논문 검색 + Core 연결 탐지"""
        papers = await self.arxiv_api.search(query, categories=["cs.CL", "cs.AI", "cs.LG"])

        for paper in papers:
            paper.is_core = False
            paper.core_connections = await self.detect_core_connections(paper)

        return papers

    async def detect_core_connections(self, paper: Paper) -> List[CoreConnection]:
        connections = []

        # 1. DOI 매칭 (프리프린트 → 출판본)
        if paper.doi:
            match = await self.db.find_core_by_doi(paper.doi)
            if match:
                connections.append(CoreConnection("published_as", match.id))

        # 2. 인용 관계
        for ref in paper.references:
            if await self.db.is_core(ref):
                connections.append(CoreConnection("cites_core", ref))

        # 3. Semantic similarity
        similar = await self.qdrant.find_similar_core(paper.embedding, threshold=0.85)
        for pid in similar:
            connections.append(CoreConnection("similar_to", pid, confidence=0.85))

        return connections
```

---

## 5. Data Flow

### 5.1 검색 요청 흐름

```
User Query: "Recent LLM evaluation benchmarks"
    │
    ▼
┌─────────────┐
│Query Service│ ─── Extract: field=NLP, topic=LLM evaluation
└─────┬───────┘
      │
      ▼
┌───────────────────────────────┐
│     Search Orchestrator       │
│  strategy: Core-first         │
└─────┬─────────────────────────┘
      │
      ├────────────────────────────┐
      ▼                            ▼
┌──────────────────┐     ┌─────────────────────┐
│  Core Corpus     │     │  On-demand          │
│  (Qdrant+PG)     │     │  (arXiv API)        │
│  ~50 results     │     │  ~20 results        │
└────────┬─────────┘     └──────────┬──────────┘
         │                          │
         │               ┌──────────┴──────────┐
         │               │ Core Connection     │
         │               │ Detection           │
         │               │ - 5 cites_core      │
         │               │ - 2 similar_to      │
         │               └──────────┬──────────┘
         │                          │
         └────────────┬─────────────┘
                      │
                      ▼
               ┌─────────────┐
               │   Merger    │
               │   Ranker    │
               │ (Core-first │
               │  boosting)  │
               └──────┬──────┘
                      │
                      ▼
               Search Result
               - 70 total papers
               - 50 Core (highlighted)
               - 20 On-demand (connection shown)
```

### 5.2 Core Corpus 수집 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                   Core Collection Pipeline                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   OpenAlex API  │  │  ACL Anthology  │  │    DBLP API     │
│ (ML/AI venues)  │  │  (NLP venues)   │  │ (IR/Legal)      │
│   ~40K papers   │  │   ~20K papers   │  │   ~5K papers    │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Deduplication  │ ─── DOI match + Title/Year
                    │   (cross-src)   │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Normalizer     │ ─── Canonical format + tier
                    └────────┬────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ PostgreSQL  │      │   Qdrant    │      │  Citation   │
│ (Core meta) │      │ (embedding) │      │   Graph     │
│ is_core=T   │      │ tier=0/1/2  │      │ (edges)     │
└─────────────┘      └─────────────┘      └─────────────┘
```

---

## 6. Scalability Considerations

### 6.1 Estimated Data Volume

| Data Type | Estimated Size |
|-----------|----------------|
| Core Papers (Tier 0+1+2) | ~65K records |
| - OpenAlex source | ~40K |
| - ACL Anthology source | ~20K |
| - DBLP source | ~5K |
| Citation Edges (Core) | ~2M edges |
| Vector Index (Core) | ~250MB |
| On-demand Cache | ~50K records (LRU) |

### 6.2 Horizontal Scaling

| Component | Scaling Strategy |
|-----------|------------------|
| API Gateway | Load balancer + multiple instances |
| Query Service | Stateless, auto-scale by CPU |
| Search Orchestrator | Stateless, auto-scale by request |
| Qdrant | Sharding by field (NLP, ML, AI) |
| PostgreSQL | Read replicas |
| Collector Workers | Queue-based, scale by backlog |

---

## 7. Technology Stack

### 7.1 Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Async**: asyncio, httpx
- **Task Queue**: Celery + Redis

### 7.2 Data Stores
- **RDBMS**: PostgreSQL 15+
- **Vector DB**: Qdrant (hybrid search: vector + BM25)
- **Cache**: Redis

### 7.3 Infrastructure
- **Container**: Docker
- **Orchestration**: Docker Compose / Kubernetes
- **CI/CD**: GitHub Actions
- **Monitoring**: Prometheus + Grafana

### 7.4 ML/NLP
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2 or SPECTER2)
- **NL Processing**: spaCy, KoNLPy (한국어)

---

## 8. Security Considerations

- API 인증: API Key 기반
- Rate limiting: 사용자별/IP별
- 입력 검증: Query injection 방지
- 외부 API 키: Secret manager 사용 (.env)
- 로깅: PII 제외

---

## 9. Failure Modes & Recovery

| Failure | Impact | Recovery |
|---------|--------|----------|
| External API down | On-demand 검색 불가 | Core-only 모드로 fallback |
| Qdrant down | 검색 불가 | PostgreSQL BM25 fallback |
| Citation graph incomplete | 연결 누락 | Incremental rebuild |
| Embedding pipeline lag | 새 논문 검색 누락 | Priority queue for Core |
