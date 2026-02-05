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
| GraphRAG integration | 🔲 Planned | Search API enhancement |

---

## Next Steps

1. **Implement `build-cited-by` command** - Pre-compute reverse citations in Qdrant
2. **Add GraphRAG search endpoint** - API for citation-aware retrieval
3. **Integrate with LLM generation** - Use expanded context for answers

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
