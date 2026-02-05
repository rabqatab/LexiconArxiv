# Search Pipeline Design

## 1. Overview

This document defines the detailed design of the **Core-first hybrid search pipeline**.

### 1.1 Key Principles

- **Core-first**: Prioritize top-tier venue papers and apply weighting
- **On-demand Extension**: Extend search to arXiv/OpenAlex when needed
- **Connection-aware**: Display Core connections for on-demand papers
- **Transparent**: Explicitly state search scope and potential gaps

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
            core_boost=2.0,  # Core paper score 2x
            fusion_method="rrf"
        )

        # Discovery query: Use both Core + On-demand
        if analysis.query_type == QueryType.DISCOVERY:
            return base.with_updates(
                ondemand_sources=["arxiv", "openalex"],
                max_core_results=200,
                max_ondemand_results=100
            )

        # Monitoring query: Emphasize latest arXiv
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
    """Search within Core Corpus (Qdrant hybrid)"""

    async def search(self, query: ExpandedQuery, strategy: SearchStrategy) -> List[CoreHit]:
        # 1. Hybrid search (vector + BM25)
        results = await self.qdrant.search(
            collection_name="paper_embeddings",
            query_vector=self.encode(query.primary),
            query_text=query.primary,  # For BM25
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
    """On-demand search (arXiv, OpenAlex)"""

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
        """arXiv API search (cs.CL, cs.AI, cs.LG, cs.IR only)"""
        papers = await self.arxiv_client.search(
            query=query.primary,
            categories=["cs.CL", "cs.AI", "cs.LG", "cs.IR"],  # Exclude Vision, Robotics
            max_results=100
        )

        return [
            OnDemandHit(
                paper_id=p.arxiv_id,
                source="arxiv",
                title=p.title,
                year=p.year,
                is_core=False,
                core_connections=[]  # Filled later
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
    """Detect Core connection relationships for on-demand papers"""

    async def detect(self, paper: OnDemandHit) -> List[CoreConnection]:
        connections = []

        # 1. DOI matching (preprint → publication)
        if paper.doi:
            core_match = await self.db.find_core_by_doi(paper.doi)
            if core_match:
                connections.append(CoreConnection(
                    type="published_as",
                    core_paper_id=core_match.id,
                    confidence=1.0
                ))

        # 2. Citation relationship detection
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
    """Core-first score fusion"""

    def fuse(
        self,
        core_results: List[CoreHit],
        ondemand_results: List[OnDemandHit],
        strategy: SearchStrategy
    ) -> List[RankedPaper]:

        # 1. Calculate base score with RRF
        all_results = core_results + ondemand_results
        rrf_scores = self._reciprocal_rank_fusion(all_results)

        # 2. Apply Core boost
        for paper in rrf_scores:
            if paper.is_core:
                paper.score *= strategy.core_boost  # Default 2.0x

            # Additional boost for Tier 0
            if paper.tier == 0:
                paper.score *= 1.2

        # 3. Recency boost (optional)
        if strategy.recency_boost:
            rrf_scores = self._apply_recency_boost(rrf_scores, strategy.recency_decay)

        # 4. Connection count boost for on-demand
        for paper in rrf_scores:
            if not paper.is_core and paper.core_connections:
                # More Core connections = higher score
                connection_boost = 1 + 0.1 * len(paper.core_connections)
                paper.score *= connection_boost

        # 5. Final sort
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

        # Phase 3: Merge - prefer Core version
        canonical = []
        for group in self._all_groups(by_doi, by_arxiv, fuzzy_groups):
            canonical.append(self._merge_prefer_core(group))

        return canonical

    def _merge_prefer_core(self, group: List[RawPaper]) -> CanonicalPaper:
        """Select Core version as primary"""
        # Prefer Core papers
        core_papers = [p for p in group if p.is_core]
        if core_papers:
            primary = core_papers[0]
        else:
            # Select the one with most complete metadata
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
    """Citation graph-based search extension"""

    async def expand_by_citations(
        self,
        seed_papers: List[str],
        depth: int = 1,
        direction: str = "both"  # "references", "citations", "both"
    ) -> List[RelatedPaper]:
        """
        Traverse citation graph from seed_papers

        Args:
            seed_papers: Starting paper ID list
            depth: Traversal depth (1 = direct citations only)
            direction: Traversal direction
        """
        visited = set(seed_papers)
        related = []

        current_level = seed_papers
        for d in range(depth):
            next_level = []

            for paper_id in current_level:
                # Core papers this paper cites
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

                # Core papers that cite this paper
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
    """Find similar papers (within Core)"""

    async def find_similar(
        self,
        paper_id: str,
        limit: int = 20,
        core_only: bool = True
    ) -> List[SimilarPaper]:
        """Find Core papers similar to a specific paper"""

        # 1. Get embedding of target paper
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
            limit=limit + 1,  # Exclude self
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
    connected_ondemand: int  # On-demand count with Core connection
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
                f"Core Corpus: {len(core_results)} papers (Tier 0/1 venue)",
                f"On-demand: {len(ondemand_results)} papers (arXiv + OpenAlex)",
                f"Core-connected On-demand: {len(connected)} papers"
            ],
            potential_gaps=[
                "Google Scholar is not included",
                "Vision/Robotics/Speech venues are excluded",
                "Latest arXiv without Core connection ranked lower"
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
        self.core_ttl = 3600      # Core results: 1 hour
        self.ondemand_ttl = 300   # On-demand: 5 minutes

    async def get_or_compute(
        self,
        query: ExpandedQuery,
        compute_fn: Callable
    ) -> SearchResult:
        # Check Core results cache
        core_key = f"core:{query.hash()}"
        cached_core = await self.redis.get(core_key)

        if cached_core:
            core_results = deserialize(cached_core)
        else:
            core_results = await compute_fn.core_search(query)
            await self.redis.setex(core_key, self.core_ttl, serialize(core_results))

        # On-demand has separate cache (shorter TTL)
        ondemand_key = f"ondemand:{query.hash()}"
        # ...

        return SearchResult(core=core_results, ondemand=ondemand_results)
```

### 8.2 Index Optimization

- **Qdrant**:
  - Core collection: m=16, ef_construct=128
  - Payload indexing: tier, field, year, is_core, keywords
  - BM25 text fields: title, abstract, keywords
  - Quantization: scalar (50% memory savings)

### 8.3 Keyword-Enhanced BM25

Using keyword field for exact paper retrieval:

```python
# Example: "HyDE paper" query
# keywords field contains ["HyDE", "dense retrieval", ...]

# BM25 search searches title + abstract + keywords
results = qdrant.search(
    collection_name="lexicon_arxiv",
    query_text="HyDE",  # BM25: matches title, abstract, keywords
    query_vector=embed("HyDE"),  # Dense: semantic similarity
    fusion="rrf",  # Reciprocal Rank Fusion
)
```

Keyword extraction methods:
- **Regex patterns**: Extract explicit acronyms from title/abstract (e.g., "BERT:", "(RAG)")
- **KeyBERT**: Extract semantic key keywords from abstracts

See [Keyword Extraction Design](./keyword_extraction.md) for details.

### 8.4 Query Timeout

```python
TIMEOUTS = {
    "core_search": 3.0,      # 3 seconds
    "arxiv": 10.0,           # 10 seconds
    "openalex": 8.0,         # 8 seconds
    "connection_detect": 2.0  # 2 seconds
}

async def search_with_fallback(tasks, timeout):
    """Always return Core results even if some fail"""
    done, pending = await asyncio.wait(tasks, timeout=timeout)

    for task in pending:
        task.cancel()

    # Always return if Core results exist
    results = [t.result() for t in done if not t.exception()]
    return results
```

---

## 9. Search Modes Summary

| Mode | Core Search | On-demand | Core Boost | Use Case |
|------|-------------|-----------|------------|----------|
| **Core-only** | Yes | No | 1.0 | Precision, verified results |
| **Core-first** | Yes | Yes | 2.0 | Default, balanced |
| **Balanced** | Yes | Yes | 1.0 | Discovery, maximum recall |
| **Monitoring** | Yes | Yes (arXiv only) | 1.5 + recency | Latest papers tracking |

---

## Related Documents

- [Architecture Overview](../architecture/overview.md)
- [Keyword Extraction](./keyword_extraction.md)
- [Citation Graph](./citation_graph.md)
- [Data Collection](./data_collection.md)
