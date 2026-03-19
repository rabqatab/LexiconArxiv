# Technical Architecture Document

## 1. System Overview

This document defines the technical architecture of the AI Research Insights Engine.

### 1.1 Architecture Principles

- **Core-first**: Use top-tier venue papers as anchors
- **On-demand Extension**: Extend search with latest papers at query time
- **Graph-aware**: Explore connections based on citation graph
- **Graceful Degradation**: Maintain Core Corpus-based search even during external API failures
- **Observability First**: Built-in metrics/logging for all pipelines

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Layer                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │   Web    │  │   CLI    │  │   API    │  │   MCP Server     │    │
│  │   App    │  │  Client  │  │  Client  │  │   (for Agents)   │    │
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
│ │(Dense+BM25)│ │  │ │  (narrow)  │ │  │ │  Graph     │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
│ ┌────────────┐ │  │                │  │ ┌────────────┐ │
│ │ Citation   │ │  │                │  │ │  Embedding │ │
│ │  Graph     │ │  │                │  │ │  Pipeline  │ │
│ └────────────┘ │  │                │  │ └────────────┘ │
│                │  │                │  │ ┌────────────┐ │
│ ┌────────────┐ │  │                │  │ │  Keyword   │ │
│ │  Ollama    │ │  │                │  │ │ Extraction │ │
│ │ (Qwen3-8B)│ │  │                │  │ └────────────┘ │
│ └────────────┘ │  │                │  │                │
└────────────────┘  └────────────────┘  └────────────────┘
```

---

## 3. Core vs On-demand Architecture

### 3.1 Core Corpus Layer

**Pre-collected top-tier venue papers** (Tier 0 + Tier 1 + Tier 2)

```
┌─────────────────────────────────────────────────────────────┐
│                     Core Corpus                              │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Tier 0      │    │ Tier 1      │    │ Tier 2      │     │
│  │ (11 venues) │───▶│ (14 venues) │───▶│ (3+ venues) │     │
│  │ ML/AI/NLP   │    │ Extended    │    │ Legal AI +  │     │
│  │             │    │             │    │ Workshops   │     │
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
│  - ACL Anthology: NLP venues (~30K papers)                  │
│  - DBLP: IR/Legal venues (~5K papers)                       │
│  - OpenReview: ICLR, NeurIPS, ICML (~15K papers)           │
│  - ACM DL: KDD, SIGIR, WWW (~10K papers)                   │
│  - AAAI OJS: AAAI (2020-2023) (~8K papers)                 │
│                                                              │
│  Storage:                                                    │
│  - PostgreSQL: Metadata, citation relationships              │
│  - Qdrant: Embedding + BM25 hybrid index                    │
│  - ~100K papers (2020-present)                              │
└─────────────────────────────────────────────────────────────┘
```

See [Venue Reference](../reference/venues.md) for complete venue details.

### 3.2 On-demand Retrieval Layer

**Extended search at query time**

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
│  - cites_core: arXiv paper cites Core                       │
│  - cited_by_core: Core cites arXiv                          │
│  - published_as: Preprint → Core publication                │
│  - similar_to: Semantic similarity                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Component Details

### 4.1 Query Service

**Responsibility**: Transform user natural language query into searchable structure

```python
class QueryService:
    def process(self, natural_query: str) -> SearchIntent:
        # 1. Language detection
        # 2. Entity extraction (venues, years, topics)
        # 3. Query expansion (synonyms, related terms)
        # 4. Search strategy selection (Core-first or balanced)
        pass
```

**Key Features**:
- Natural language parsing (English/Korean support)
- Year/venue/field extraction
- Query expansion (synonyms, related terms)
- Search strategy decision (Core-only, Core-first, Balanced)

### 4.2 Search Orchestrator

**Responsibility**: Coordinate Core + On-demand search and integrate results

```python
class SearchOrchestrator:
    async def search(self, intent: SearchIntent) -> SearchResult:
        # 1. Core Corpus search (primary)
        core_results = await self.core_index.search(intent)

        # 2. On-demand extension (if needed)
        if intent.include_ondemand:
            ondemand_results = await asyncio.gather(
                self.arxiv_client.search(intent),
                self.openalex_client.narrow_search(intent),
            )

            # 3. Core connection detection
            for paper in ondemand_results:
                paper.core_connections = await self.detect_connections(paper)

        # 4. Result integration and ranking
        merged = self.merger.merge(core_results, ondemand_results)
        ranked = self.ranker.rank(merged, intent.ranking_strategy)

        # 5. Apply Core-first weighting
        ranked = self.apply_core_boost(ranked)

        return SearchResult(papers=ranked, core_count=len(core_results))
```

### 4.3 Graph Service

**Responsibility**: Citation graph exploration and trend analysis

```python
class GraphService:
    async def get_citation_network(self, paper_id: str, depth: int = 2) -> CitationGraph:
        """Return citation network for a specific paper"""
        # 1. Core papers this paper cites
        references = await self.db.get_references(paper_id, core_only=True)

        # 2. Papers that cite this paper
        citations = await self.db.get_citations(paper_id, core_only=True)

        # 3. Build graph
        return CitationGraph(
            center=paper_id,
            references=references,
            citations=citations,
            depth=depth
        )

    async def get_field_trends(self, field: str, years: int = 5) -> TrendAnalysis:
        """Analyze trends by field"""
        # 1. Paper count by year
        # 2. Keyword changes
        # 3. Notable paper selection (high citations, recent surge)
        pass

    async def find_notable_papers(self, field: str, limit: int = 20) -> List[Paper]:
        """Automatic notable paper selection"""
        # Criteria: citation count, venue tier, recency, citation velocity
        pass
```

### 4.4 Search Service

**Responsibility**: Orchestrate query embedding and Qdrant hybrid search

```python
class SearchService:
    """Orchestrates hybrid search: embed query + Qdrant prefetch + RRF fusion."""
    async def search(self, query, venues, year_min, year_max, tiers, limit) -> dict:
        # 1. Embed query via Ollama (instruction-aware)
        # 2. Prefetch: dense (Qwen3-8B) + sparse (BM25)
        # 3. Fuse with RRF
        # 4. Falls back to BM25-only if Ollama unavailable
```

**Hybrid search flow**:
1. Embed the query via Ollama `/api/embed` with instruction prefix `"Retrieve academic papers: "`
2. Issue two Qdrant `Prefetch` legs in parallel: dense vector search on the `abstract-qwen3-8b` named vector, and BM25 sparse search via `qdrant/bm25` Document inference
3. Fuse results with Reciprocal Rank Fusion (RRF)
4. If Ollama is unreachable, fall back to BM25-only search transparently

### 4.5 Core Corpus Layer

#### PostgreSQL (Metadata + Graph Store)
- Core paper records (tier 0/1/2)
- Citation edges (referenced_works)
- Core connections for on-demand papers
- Authors and venues

#### Qdrant (Hybrid Index)
- Dense vector search (1024-dim Qwen3-Embedding-8B via MRL from 4096d)
- BM25 sparse search (server-side via `qdrant/bm25` Document inference)
- Named vectors: `abstract-qwen3-8b` (dense), `bm25` (sparse)
- Payload filtering (tier, venue, year, keywords)
- Collection migrated from payload-only to named-vector schema

#### Ollama (Embedding Server)
- Serves Qwen3-Embedding-8B for both batch embedding and query-time embedding
- Instruction-aware: prepends task instruction for retrieval quality

### 4.6 MCP Server

**Responsibility**: Expose search and paper tools to AI agents via Model Context Protocol

The MCP server wraps `SearchService` and provides four tools: `search_papers`, `get_paper`, `get_citations`, and `get_corpus_stats`. It communicates over stdio and is compatible with Claude Desktop, Claude Code, and other MCP clients.

### 4.7 On-demand Retrieval

```python
class OnDemandRetriever:
    async def search_arxiv(self, query: str) -> List[Paper]:
        """Search arXiv latest papers + Core connection detection"""
        papers = await self.arxiv_api.search(query, categories=["cs.CL", "cs.AI", "cs.LG"])

        for paper in papers:
            paper.is_core = False
            paper.core_connections = await self.detect_core_connections(paper)

        return papers

    async def detect_core_connections(self, paper: Paper) -> List[CoreConnection]:
        connections = []

        # 1. DOI matching (preprint → publication)
        if paper.doi:
            match = await self.db.find_core_by_doi(paper.doi)
            if match:
                connections.append(CoreConnection("published_as", match.id))

        # 2. Citation relationship
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

### 5.1 Search Request Flow

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

### 5.2 Core Corpus Collection Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   Core Collection Pipeline                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   OpenAlex API  │  │  ACL Anthology  │  │    DBLP API     │
│ (ML/AI venues)  │  │  (NLP venues)   │  │ (IR/Legal)      │
│   ~40K papers   │  │   ~30K papers   │  │   ~5K papers    │
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
| Core Papers (Tier 0+1+2) | ~100K records |
| Citation Edges (Core) | ~3M edges |
| Vector Index (Core) | ~400MB |
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
- **Language**: Python 3.12+
- **Framework**: FastAPI
- **Async**: asyncio, httpx
- **Rate Limiting**: slowapi (per-IP)
- **Task Queue**: Celery + Redis
- **MCP**: mcp SDK (stdio transport for AI agent integration)

### 7.2 Data Stores
- **RDBMS**: PostgreSQL 15+
- **Vector DB**: Qdrant (hybrid search: dense + BM25, named vectors)
- **Cache**: Redis

### 7.3 Infrastructure
- **Container**: Docker
- **Orchestration**: Docker Compose / Kubernetes
- **CI/CD**: GitHub Actions
- **Monitoring**: Prometheus + Grafana

### 7.4 ML/NLP
- **Embeddings**: Qwen3-Embedding-8B via Ollama (1024d via MRL from 4096d, instruction-aware)
- **BM25**: Server-side sparse vectors via Qdrant `qdrant/bm25` Document inference
- **Keyword Extraction**: LLM-first (Gemini/Ollama) with KeyBERT fallback
- **Clustering**: UMAP + HDBSCAN (for trend analysis)
- **NL Processing**: spaCy

---

## 8. Security Considerations

- API authentication: API Key based
- Rate limiting: Per user/IP
- Input validation: Query injection prevention
- External API keys: Use secret manager (.env)
- Logging: Exclude PII

---

## 9. Failure Modes & Recovery

| Failure | Impact | Recovery |
|---------|--------|----------|
| External API down | On-demand search unavailable | Fallback to Core-only mode |
| Qdrant down | Search unavailable | PostgreSQL BM25 fallback |
| Citation graph incomplete | Missing connections | Incremental rebuild |
| Embedding pipeline lag | New papers not searchable | Priority queue for Core |

---

## Related Documents

- [Data Model](./data_model.md)
- [API Specification](./api.md)
- [Search Pipeline](../pipelines/search.md)
- [Embedding Pipeline](../pipelines/embedding.md)
- [Data Collection](../pipelines/data_collection.md)
