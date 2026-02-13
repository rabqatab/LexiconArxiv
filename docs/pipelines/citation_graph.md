# Citation Graph Design

## Overview

This document describes the citation graph architecture for LexiconArxiv, enabling:

1. **Reverse Citation Lookup** - "Which papers cite this paper?"
2. **Graph Export** - CSV, JSON, GraphML, GEXF formats for visualization
3. **Graph Analysis** - PageRank, HITS, community detection
4. **GraphRAG Integration** - Citation-aware context expansion for LLM generation

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Citation Graph Pipeline                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────────┐    ┌─────────────────┐    ┌────────────────────────┐│
│  │   Enrichment  │───▶│  Reference      │───▶│  Qdrant Storage        ││
│  │   Pipeline    │    │  Resolution     │    │                        ││
│  │               │    │                 │    │  • resolved_references ││
│  │ OpenAlex refs │    │ DOI → point_id  │    │  • cited_by            ││
│  │ PDF GROBID    │    │ Title matching  │    │                        ││
│  └───────────────┘    └─────────────────┘    └───────────┬────────────┘│
│                                                          │              │
│                                              ┌───────────▼────────────┐│
│                                              │   Citation Graph       ││
│                                              │   Module               ││
│                                              │                        ││
│                                              │ • ReverseCitationIndex ││
│                                              │ • CitationGraphBuilder ││
│                                              │ • GraphExporter        ││
│                                              │ • GraphAnalyzer        ││
│                                              └───────────┬────────────┘│
│                                                          │              │
│                    ┌─────────────────────────────────────┼─────────────┐
│                    │                                     │             │
│                    ▼                                     ▼             │
│          ┌─────────────────┐                   ┌─────────────────────┐ │
│          │  Graph Export   │                   │  GraphRAG Context   │ │
│          │                 │                   │                     │ │
│          │ • CSV (Gephi)   │                   │ Query → Top K papers│ │
│          │ • JSON (D3.js)  │                   │ → Expand citations  │ │
│          │ • GraphML       │                   │ → LLM generation    │ │
│          │ • GEXF          │                   │                     │ │
│          └─────────────────┘                   └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Qdrant Schema Extension

Papers in Qdrant have the following citation-related fields:

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `referenced_works` | `list[str]` | External IDs (OpenAlex, DOI) of cited papers | Enrichment |
| `resolved_references` | `list[str]` | Qdrant point IDs of cited papers (in-corpus) | Reference Resolution |
| `cited_by` | `list[str]` | Qdrant point IDs of papers citing this paper | `build-cited-by` |
| `pagerank` | `float` | PageRank score (0-1) | Graph Analysis |
| `hub_score` | `float` | HITS hub score | Graph Analysis |
| `authority_score` | `float` | HITS authority score | Graph Analysis |
| `community_id` | `int` | Louvain community cluster ID | Graph Analysis |
| `is_stub` | `bool` | `true` if external paper (no embedding) | Stub Creation |
| `identifier` | `str` | Raw identifier for stubs (e.g., `doi:10.xxx`) | Stub Creation |
| `identifier_type` | `str` | Type: `doi`, `arxiv`, `title`, `openalex` | Stub Creation |
| `cited_by_count_internal` | `int` | Count of corpus papers citing this stub | Stub Creation |

---

## Module Structure

```
src/core/citation_graph/
    __init__.py           # Module exports
    reverse_index.py      # ReverseCitationIndex class
    builder.py            # CitationGraphBuilder class
    exporter.py           # GraphExporter, StreamingGraphExporter
    analyzer.py           # GraphAnalyzer, GraphMetrics
```

---

## Components

### 1. ReverseCitationIndex

Builds an in-memory reverse citation index from `resolved_references`.

```python
class ReverseCitationIndex:
    """Build reverse citation lookup from resolved_references."""

    def build_index(self, include_metadata: bool = True) -> None
    def get_citing_papers(self, paper_id: str) -> list[str]
    def get_cited_papers(self, paper_id: str) -> list[str]
    def get_citation_count(self, paper_id: str) -> int
    def iter_all_edges(self) -> Iterator[tuple[str, str]]
    def get_stats(self) -> dict
```

**Memory Considerations:**

| Graph Size | With Metadata | Without Metadata |
|------------|---------------|------------------|
| 100K nodes, 5M edges | ~1.5 GB | ~900 MB |
| 150K nodes, 10M edges | ~2.5 GB | ~1.5 GB |

Use `include_metadata=False` to reduce memory by ~40%.

### 2. CitationGraphBuilder

Builds NetworkX graphs for analysis and export.

```python
class CitationGraphBuilder:
    """Build NetworkX DiGraph from Qdrant data."""

    def build_graph(
        self,
        filter_venues: list[str] | None = None,
        filter_years: tuple[int, int] | None = None,
    ) -> nx.DiGraph

    def build_subgraph(
        self,
        center_paper_id: str,
        hops: int = 2,
        direction: str = "both",  # "both", "citing", "cited"
    ) -> nx.DiGraph
```

**Edge Direction:** `citing_paper → cited_paper` (A cites B means edge A→B)

### 3. GraphExporter

Exports graphs to various formats.

```python
class GraphExporter:
    """Export citation graph to various formats."""

    def to_csv_edgelist(self, output_path: Path) -> int
    def to_csv_nodes(self, output_path: Path) -> int
    def to_json(self, output_path: Path) -> dict
    def to_graphml(self, output_path: Path) -> None
    def to_gexf(self, output_path: Path) -> None
```

**StreamingGraphExporter** for large graphs (>1M edges):

```python
class StreamingGraphExporter:
    """Memory-efficient streaming export directly from Qdrant."""

    def export_edges_csv(self, output_path: Path) -> int
    def export_nodes_csv(self, output_path: Path) -> int
```

### 4. GraphAnalyzer

Computes graph metrics and centrality measures.

```python
class GraphAnalyzer:
    """Compute graph metrics."""

    def compute_global_metrics(self) -> GraphMetrics
    def compute_pagerank(self, alpha: float = 0.85) -> dict[str, float]
    def compute_hits(self) -> tuple[dict, dict]  # hubs, authorities
    def compute_communities(self) -> dict[str, int]
    def store_metrics_to_qdrant(self) -> int
```

**Metrics Computed:**

| Metric | Description | Use Case |
|--------|-------------|----------|
| PageRank | Citation flow importance | Identify influential papers |
| Hub Score | Cites many important papers | Find survey/review papers |
| Authority Score | Cited by many hubs | Find foundational papers |
| Community ID | Louvain clustering | Identify research topics |

---

## GraphRAG Integration

### The Problem

Standard RAG retrieves papers by semantic similarity alone. Citation context is lost:
- A highly-cited foundational paper may not match the query embedding
- Survey papers that synthesize a field aren't discovered
- Citation chains showing research evolution are invisible

### The Solution: `cited_by` Field

Store reverse citations directly in Qdrant for O(1) bidirectional traversal:

```python
# Each paper has both directions:
{
    "resolved_references": ["id1", "id2", ...],  # papers this paper cites
    "cited_by": ["id3", "id4", ...],             # papers that cite this paper
}
```

### GraphRAG Query Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           GraphRAG Query Flow                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. QUERY                                                                │
│     ┌──────────────────┐                                                │
│     │ "What are recent │                                                │
│     │ advances in RLHF │                                                │
│     │ for LLMs?"       │                                                │
│     └────────┬─────────┘                                                │
│              │                                                           │
│  2. EMBEDDING SEARCH                                                     │
│              ▼                                                           │
│     ┌──────────────────┐    Top K papers by semantic similarity         │
│     │  Qdrant Vector   │───▶ Paper A: "RLHF for Language Models"        │
│     │     Search       │    Paper B: "PPO for LLM Alignment"            │
│     └────────┬─────────┘    Paper C: "Constitutional AI"                │
│              │                                                           │
│  3. CITATION EXPANSION (1-hop)                                          │
│              ▼                                                           │
│     ┌──────────────────┐                                                │
│     │ For each paper:  │                                                │
│     │                  │                                                │
│     │ cited_by[A] ────▶ Papers citing A (newer work)                    │
│     │ resolved_refs[A]▶ Papers A cites (foundational)                   │
│     │                  │                                                │
│     │ Union all papers │                                                │
│     └────────┬─────────┘                                                │
│              │                                                           │
│  4. CONTEXT ASSEMBLY                                                     │
│              ▼                                                           │
│     ┌──────────────────┐                                                │
│     │ Expanded context:│                                                │
│     │ • Top K papers   │                                                │
│     │ • Their citations│    15-30 papers total                          │
│     │ • Citing papers  │    (deduplicated)                              │
│     └────────┬─────────┘                                                │
│              │                                                           │
│  5. LLM GENERATION                                                       │
│              ▼                                                           │
│     ┌──────────────────┐                                                │
│     │ Generate answer  │    With citation-enriched context              │
│     │ with full        │    LLM can reference citation chains           │
│     │ citation context │    and research evolution                      │
│     └──────────────────┘                                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
async def graphrag_search(
    query: str,
    top_k: int = 5,
    citation_hops: int = 1,
    max_context_papers: int = 30,
) -> list[Paper]:
    """Retrieve papers with citation context expansion."""

    # 1. Embedding search
    query_embedding = await embed(query)
    top_papers = await qdrant.search(query_embedding, limit=top_k)

    # 2. Citation expansion
    context_ids = set(p.id for p in top_papers)

    for paper in top_papers:
        # Add papers this paper cites (foundational work)
        context_ids.update(paper.payload.get("resolved_references", []))

        # Add papers citing this paper (follow-up work)
        context_ids.update(paper.payload.get("cited_by", []))

    # 3. Fetch full context
    context_papers = await qdrant.retrieve(
        list(context_ids)[:max_context_papers]
    )

    # 4. Rank by relevance + citation importance
    return rank_by_relevance_and_pagerank(context_papers, query_embedding)
```

### Why Not a Separate GraphDB?

| Approach | Pros | Cons |
|----------|------|------|
| **Qdrant only** (chosen) | Single data store, no sync, O(1) lookups | Limited to 1-2 hop queries |
| **Neo4j** | Complex traversals, Cypher queries | Extra infra, sync complexity |
| **NetworkX in-memory** | Full graph algorithms | 2-3 GB RAM for 150K nodes |

For GraphRAG with 1-2 hop expansion, storing `cited_by` in Qdrant is sufficient and simpler.

---

## CLI Commands

### Graph Building & Export

```bash
# Build and export full graph
python -m src.cli.core_collect build-citation-graph -o graph.json

# Export for Gephi visualization
python -m src.cli.core_collect build-citation-graph -o graph.graphml --format graphml

# Filter by venue
python -m src.cli.core_collect build-citation-graph -v ACL -v EMNLP -o nlp_graph.json

# Large graph: use streaming export (low memory)
python -m src.cli.core_collect build-citation-graph -o /tmp/graph --streaming
```

### Graph Analysis

```bash
# Compute all metrics and show top papers
python -m src.cli.core_collect analyze-citation-graph --all --top-n 50

# Compute PageRank and store to Qdrant
python -m src.cli.core_collect analyze-citation-graph --compute-pagerank --store

# Detect communities
python -m src.cli.core_collect analyze-citation-graph --compute-communities
```

### Reverse Citation Lookup

```bash
# Get papers citing a specific paper
python -m src.cli.core_collect get-citing-papers <point_id>

# Export 2-hop neighborhood
python -m src.cli.core_collect export-graph-subgraph <point_id> --hops 2 -o subgraph.json
```

### GraphRAG Preparation

```bash
# Build cited_by field for all papers (required for GraphRAG)
python -m src.cli.core_collect build-cited-by

# Check citation graph statistics
python -m src.cli.core_collect citation-graph-stats
```

---

## Memory & Performance

### Estimation

```python
from src.core.citation_graph import estimate_memory_mb

# Estimate before building
est = estimate_memory_mb(
    num_papers=150000,
    num_edges=10000000,
    include_metadata=True
)
print(f"Estimated memory: {est} MB")
```

### Recommendations

| Use Case | Recommendation |
|----------|----------------|
| Full graph analysis | Ensure 4+ GB RAM, use `--no-metadata` if tight |
| Export for Gephi | Use `--streaming` for graphs >1M edges |
| GraphRAG queries | Pre-compute `cited_by` field, O(1) lookups |
| PageRank/HITS | Compute once, store to Qdrant |

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| ReverseCitationIndex | ✅ Complete | With memory estimation |
| CitationGraphBuilder | ✅ Complete | Supports filtering |
| GraphExporter | ✅ Complete | CSV, JSON, GraphML, GEXF |
| StreamingGraphExporter | ✅ Complete | Low-memory CSV export |
| GraphAnalyzer | ✅ Complete | PageRank, HITS, communities |
| CLI commands | ✅ Complete | 6 commands |
| `cited_by` field | ✅ Complete | `build-cited-by` command |
| Stub paper creation | ✅ Complete | `resolve-refs` (stubs created by default) |
| Stub enrichment | ✅ Complete | `enrich-stubs` with deduplication |
| `stub-stats` command | ✅ Complete | Most-cited external papers |
| Stub deduplication | ✅ Complete | Cross-reference merge during enrichment |
| GraphRAG integration | 🔲 Planned | Search API enhancement |

---

## Stub Papers (External References)

### Overview

**Stub papers** (or "ghost papers") are external papers that appear in references but don't exist in the core corpus. Storing them enables:

1. **Complete citation graph** - See full network, not just internal edges
2. **Corpus expansion hints** - Identify most-cited external papers to prioritize crawling
3. **Better PageRank** - External influential papers get proper scores
4. **Research gap analysis** - See which foundational papers are missing

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Citation Resolution with Stub Papers                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Paper A references: [doi:10.1234/in-corpus, doi:10.5678/external]      │
│                            ↓                        ↓                    │
│                      ┌─────────────┐         ┌─────────────┐            │
│                      │ RESOLVED    │         │ STUB PAPER  │            │
│                      │ (exists)    │         │ (created)   │            │
│                      │             │         │             │            │
│                      │ is_stub:    │         │ is_stub:    │            │
│                      │   false     │         │   true      │            │
│                      │ vector: ✓   │         │ vector: ✗   │            │
│                      └─────────────┘         └─────────────┘            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Schema

Stub papers are stored in the same collection with `is_stub: true`:

| Field | Crawled Paper | Stub Paper |
|-------|---------------|------------|
| `is_stub` | `false` | `true` |
| `identifier` | - | `"doi:10.1234/..."` |
| `identifier_type` | - | `"doi"`, `"title"`, `"arxiv"` |
| `title` | Full title | `null` (until enriched) |
| `abstract` | Full abstract | `null` (until enriched) |
| `vector` | Embedding ✓ | `null` (no embedding) |
| `cited_by` | Papers citing this | Papers citing this |
| `cited_by_count_internal` | - | Count of corpus papers citing |

### Why No Embeddings for Stubs?

| Factor | Crawled Papers | Stubs |
|--------|---------------|-------|
| Content | Full abstract (500+ words) | Title only or nothing |
| Embedding quality | High | Low/meaningless |
| Search relevance | Primary use case | Not needed |
| Purpose | Semantic search | Graph analysis only |

Stubs exist for **citation graph analysis**, not semantic search. Mixing low-quality embeddings would degrade search results.

### Expected Numbers

```
Your corpus:           ~10,000 papers
Total references:      ~400,000
Internal (resolved):   ~3,000 edges
External (stubs):      ~100,000 unique papers (after dedup)
```

Many papers cite the same foundational works, so deduplication significantly reduces stub count.

### CLI Commands

```bash
# Create stub papers during resolution
python -m src.cli.core_collect resolve-refs

# Show stub statistics and most-cited external papers
python -m src.cli.core_collect stub-stats

# Enrich stubs with metadata from OpenAlex/CrossRef
python -m src.cli.core_collect enrich-stubs --limit 1000

# Promote enriched stubs to full papers (with embedding)
python -m src.cli.core_collect promote-stubs --min-citations 10
```

### Stub Statistics Example

```
=== Stub Paper Statistics ===

Total stubs:              52,847
Stubs with DOI:           38,291 (72%)
Stubs with title only:    14,556 (28%)

=== Most Cited External Papers ===

Rank  Citations  Identifier
────  ─────────  ──────────────────────────────────────────
1     156        doi:10.5555/3295222.3295349 (Attention Is All...)
2     134        doi:10.18653/v1/N19-1423 (BERT)
3     98         doi:10.48550/arXiv.1810.04805 (BERT original)
4     87         doi:10.1145/3394486.3403149 (GPT-3)
5     76         doi:10.18653/v1/D14-1162 (GloVe)
...

=== Recommendations ===

Consider adding these highly-cited external papers to your corpus:
  python -m src.cli.core_collect collect-by-doi doi:10.5555/3295222.3295349
```

### Query Patterns

```python
# Search only real papers (exclude stubs from semantic search)
results = qdrant.search(
    query_vector=embedding,
    query_filter=Filter(must=[
        FieldCondition(key="is_stub", match=MatchValue(value=False))
    ])
)

# Find most-cited external papers (stubs)
stubs = qdrant.scroll(
    scroll_filter=Filter(must=[
        FieldCondition(key="is_stub", match=MatchValue(value=True))
    ]),
    order_by=OrderBy(key="cited_by_count_internal", direction="desc"),
    limit=100
)

# Get complete citation graph (including stubs)
all_edges = qdrant.scroll(
    with_payload=["resolved_references"],
    # No filter - includes both real and stub papers
)
```

### Stub Enrichment Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Stub Enrichment Flow                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Phase 1: Create minimal stubs during resolution                        │
│  ─────────────────────────────────────────────                          │
│  {                                                                       │
│    "identifier": "doi:10.18653/v1/N19-1423",                            │
│    "is_stub": true,                                                      │
│    "cited_by": ["uuid1", "uuid2", ...],                                 │
│    "cited_by_count_internal": 134                                       │
│  }                                                                       │
│                                                                          │
│  Phase 2: Enrich from OpenAlex/CrossRef (async)                         │
│  ───────────────────────────────────────────────                        │
│  {                                                                       │
│    "identifier": "doi:10.18653/v1/N19-1423",                            │
│    "is_stub": true,                                                      │
│    "title": "BERT: Pre-training of Deep Bidirectional...",              │
│    "year": 2019,                                                         │
│    "authors": ["Jacob Devlin", ...],                                    │
│    "venue": "NAACL",                                                     │
│    "citation_count": 95000,  // Global citation count                   │
│    "cited_by": ["uuid1", "uuid2", ...],                                 │
│    "cited_by_count_internal": 134                                       │
│  }                                                                       │
│                                                                          │
│  Phase 3 (Optional): Promote to full paper                              │
│  ─────────────────────────────────────────                              │
│  If stub has full abstract → embed and set is_stub=false                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stub Deduplication

### The Problem

The same external paper can be referenced with different identifiers:
- Paper A cites "Attention Is All You Need" via `DOI:10.xxx`
- Paper B cites the same paper via `arXiv:1706.03762`

Without deduplication, these create two separate stubs with split citation counts.

### Solution: Cross-Reference Merge

During enrichment, when we discover additional identifiers for a stub:

1. **Discover identifiers** - OpenAlex returns DOI, arXiv ID, and OpenAlex ID
2. **Check for duplicates** - Search existing stubs with those identifiers
3. **Merge if found** - Combine `cited_by` lists, store alternate identifiers

```
Before: arXiv stub (5 citations) + DOI stub (5 citations)
After:  Single stub (10 citations) with alternate_identifiers
```

### Storage Schema

Stubs now include `alternate_identifiers` for cross-reference:

```json
{
  "identifier": "W1522301498",
  "identifier_type": "openalex",
  "alternate_identifiers": {
    "doi": "10.48550/arxiv.1412.6980",
    "arxiv": "1412.6980"
  },
  "cited_by_count_internal": 10
}
```

### CLI Commands

```bash
# Enrichment automatically deduplicates
python -m src.cli.core_collect enrich-stubs --limit 1000

# Check merge results
python -m src.cli.core_collect stub-stats
```

---

## Next Steps

1. ~~**Implement `build-cited-by` command**~~ ✅ Complete
2. ~~**Implement stub paper creation**~~ ✅ Complete
3. ~~**Add `stub-stats` command**~~ ✅ Complete
4. ~~**Add `enrich-stubs` command**~~ ✅ Complete
5. ~~**Add stub deduplication**~~ ✅ Complete
6. **Add GraphRAG search endpoint** - API for citation-aware retrieval
7. **Add title-based stub deduplication** - Fuzzy match TITLE stubs against enriched stubs

---

## Dependencies

```toml
# pyproject.toml
networkx = ">=3.0"
```

---

## References

- [NetworkX Documentation](https://networkx.org/)
- [Gephi](https://gephi.org/) - Graph visualization
- [GraphRAG Paper](https://arxiv.org/abs/2404.16130) - Microsoft's GraphRAG approach
