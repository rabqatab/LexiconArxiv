# API Specification

## 1. Overview

This document defines the REST API and MCP interface for the AI/NLP paper search engine.

**Base URL**: `https://api.lexiconarxiv.io/v1`

**Authentication**: API Key (Header: `X-API-Key`)

---

## 2. REST API Endpoints

### 2.1 Search API

#### POST /search

Natural language paper search

**Request**:
```json
{
  "query": "Korean LLM instruction tuning datasets",
  "options": {
    "sources": ["openalex", "arxiv", "acl"],
    "year_from": 2022,
    "year_to": null,
    "venues": ["ACL", "EMNLP", "NAACL"],
    "paper_types": ["dataset", "benchmark"],
    "preprint_only": false,
    "published_only": false,
    "limit": 100,
    "offset": 0,
    "ranking": "relevance"
  }
}
```

**Request Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Natural language search query |
| `options.sources` | string[] | No | Search sources (default: all) |
| `options.year_from` | int | No | Start year filter |
| `options.year_to` | int | No | End year filter |
| `options.venues` | string[] | No | Venue/journal filter |
| `options.paper_types` | string[] | No | Paper type filter |
| `options.preprint_only` | bool | No | Preprints only |
| `options.published_only` | bool | No | Published papers only |
| `options.limit` | int | No | Result count (default: 50, max: 500) |
| `options.offset` | int | No | Pagination offset |
| `options.ranking` | string | No | Ranking method |

**Search Mode Options** (NEW):
- `core_only`: Search Core Corpus (Tier 0/1) only
- `core_first`: Core priority + On-demand expansion (default)
- `balanced`: Core + On-demand equal weight
- `monitoring`: Emphasize recent arXiv papers

**Ranking Options**:
- `relevance`: Relevance score (default, includes Core boost)
- `recency`: Most recent first
- `citation`: Citation count order
- `venue_tier`: Venue tier order (Tier 0 > Tier 1 > others)
- `hybrid_rrf`: Reciprocal Rank Fusion

**Response**:
```json
{
  "results": [
    {
      "id": "paper_abc123",
      "title": "KULLM: Korean Large Language Model",
      "authors": [
        {"name": "Kim et al.", "affiliation": "KAIST"}
      ],
      "abstract": "We present KULLM, a Korean instruction-tuned...",
      "year": 2023,
      "venue": "arXiv preprint",
      "paper_type": "method",
      "identifiers": {
        "doi": null,
        "arxiv_id": "2304.12345",
        "acl_id": null,
        "openalex_id": "W1234567890"
      },
      "urls": {
        "pdf": "https://arxiv.org/pdf/2304.12345",
        "abstract": "https://arxiv.org/abs/2304.12345"
      },
      "versions": [
        {
          "type": "preprint",
          "source": "arxiv",
          "date": "2023-04-15"
        }
      ],
      "scores": {
        "relevance": 0.92,
        "bm25": 45.3,
        "semantic": 0.88
      },
      "is_core": false,
      "tier": null,
      "core_connections": [
        {"type": "cites_core", "paper_id": "W987654321", "confidence": 1.0},
        {"type": "similar_to", "paper_id": "W123456789", "confidence": 0.87}
      ],
      "source_matched": ["arxiv", "openalex"]
    }
  ],
  "total_count": 623,
  "returned_count": 100,
  "transparency": {
    "sources_searched": ["openalex", "arxiv", "acl"],
    "raw_counts": {
      "openalex": 450,
      "arxiv": 280,
      "acl": 95
    },
    "after_dedup": 623,
    "search_strategy": "hybrid_bm25_semantic",
    "coverage_note": "Google Scholar/Semantic Scholar not included",
    "execution_time_ms": 1250
  },
  "pagination": {
    "limit": 100,
    "offset": 0,
    "has_more": true
  }
}
```

---

#### GET /search/suggest

Query autocomplete and suggestions

**Request**:
```
GET /search/suggest?q=instruction+tun&limit=5
```

**Response**:
```json
{
  "suggestions": [
    {
      "text": "instruction tuning",
      "type": "topic",
      "count": 1523
    },
    {
      "text": "instruction tuning dataset",
      "type": "topic",
      "count": 342
    }
  ]
}
```

---

### 2.2 Paper API

#### GET /papers/{paper_id}

Single paper details

**Response**:
```json
{
  "id": "paper_abc123",
  "title": "KULLM: Korean Large Language Model",
  "authors": [
    {
      "name": "Seungjun Lee",
      "affiliation": "KAIST",
      "orcid": "0000-0001-2345-6789"
    }
  ],
  "abstract": "Full abstract text...",
  "year": 2023,
  "month": 4,
  "venue": {
    "name": "arXiv",
    "type": "preprint"
  },
  "paper_type": "method",
  "keywords": ["LLM", "Korean", "instruction tuning"],
  "identifiers": {
    "doi": null,
    "arxiv_id": "2304.12345",
    "acl_id": null,
    "openalex_id": "W1234567890"
  },
  "urls": {
    "pdf": "https://arxiv.org/pdf/2304.12345",
    "abstract": "https://arxiv.org/abs/2304.12345",
    "code": "https://github.com/nlpai-lab/KULLM"
  },
  "versions": [
    {
      "type": "preprint",
      "source": "arxiv",
      "version": "v2",
      "date": "2023-04-20"
    }
  ],
  "related_papers": {
    "preprint_of": null,
    "published_as": null,
    "extended_version": null
  },
  "citation_count": 45,
  "last_updated": "2024-01-15T10:30:00Z"
}
```

---

#### GET /papers/{paper_id}/versions

All versions of a paper (preprint, camera-ready, journal, etc.)

**Response**:
```json
{
  "canonical_id": "paper_abc123",
  "versions": [
    {
      "id": "paper_abc123_v1",
      "type": "preprint",
      "source": "arxiv",
      "arxiv_id": "2304.12345v1",
      "date": "2023-04-15",
      "title": "KULLM: Korean Large Language Model"
    },
    {
      "id": "paper_abc123_v2",
      "type": "conference",
      "source": "acl",
      "acl_id": "2023.emnlp-main.123",
      "date": "2023-12-06",
      "venue": "EMNLP 2023",
      "title": "KULLM: Effective Korean Instruction Tuning"
    }
  ]
}
```

---

### 2.3 Export API

#### POST /export

Export search results

**Request**:
```json
{
  "paper_ids": ["paper_abc123", "paper_def456"],
  "format": "bibtex",
  "options": {
    "include_abstract": true,
    "include_urls": true
  }
}
```

**Supported Formats**:
- `bibtex`: BibTeX format
- `csv`: CSV with configurable columns
- `json`: Full JSON export
- `ris`: RIS format (EndNote compatible)

**Response** (BibTeX):
```
@article{lee2023kullm,
  title={KULLM: Korean Large Language Model},
  author={Lee, Seungjun and Kim, ...},
  journal={arXiv preprint arXiv:2304.12345},
  year={2023},
  abstract={We present KULLM...},
  url={https://arxiv.org/abs/2304.12345}
}
```

---

### 2.4 Saved Query API

#### POST /queries

Create saved search query

**Request**:
```json
{
  "name": "RAG Evaluation Monitoring",
  "query": "RAG evaluation benchmark",
  "options": {
    "sources": ["arxiv"],
    "year_from": 2024
  },
  "schedule": {
    "frequency": "daily",
    "notify": true
  }
}
```

#### GET /queries

List saved search queries

#### GET /queries/{query_id}/results

Latest results for saved query

#### DELETE /queries/{query_id}

Delete saved query

---

## 3. MCP Server Interface

MCP (Model Context Protocol) server for AI Agent integration

### 3.1 Tools

#### search_papers

```json
{
  "name": "search_papers",
  "description": "Search for academic papers in AI/NLP domain with maximum recall",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language search query"
      },
      "year_from": {
        "type": "integer",
        "description": "Filter papers from this year"
      },
      "limit": {
        "type": "integer",
        "default": 50,
        "description": "Maximum number of results"
      }
    },
    "required": ["query"]
  }
}
```

#### get_paper_details

```json
{
  "name": "get_paper_details",
  "description": "Get detailed information about a specific paper",
  "inputSchema": {
    "type": "object",
    "properties": {
      "paper_id": {
        "type": "string",
        "description": "Paper ID from search results"
      }
    },
    "required": ["paper_id"]
  }
}
```

#### export_papers

```json
{
  "name": "export_papers",
  "description": "Export papers to BibTeX/CSV/JSON format",
  "inputSchema": {
    "type": "object",
    "properties": {
      "paper_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of paper IDs to export"
      },
      "format": {
        "type": "string",
        "enum": ["bibtex", "csv", "json"],
        "default": "bibtex"
      }
    },
    "required": ["paper_ids"]
  }
}
```

### 3.2 Resources

```json
{
  "resources": [
    {
      "uri": "papers://recent",
      "name": "Recent AI/NLP Papers",
      "description": "Latest papers from the past week"
    },
    {
      "uri": "papers://trending",
      "name": "Trending Papers",
      "description": "Most accessed papers this month"
    }
  ]
}
```

---

## 4. Error Handling

### 4.1 Error Response Format

```json
{
  "error": {
    "code": "INVALID_QUERY",
    "message": "Query cannot be empty",
    "details": {
      "field": "query",
      "constraint": "min_length:1"
    }
  },
  "request_id": "req_abc123"
}
```

### 4.2 Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_QUERY` | 400 | Invalid search query |
| `INVALID_FILTER` | 400 | Invalid filter value |
| `UNAUTHORIZED` | 401 | API key missing or invalid |
| `RATE_LIMITED` | 429 | Request rate limit exceeded |
| `SOURCE_UNAVAILABLE` | 503 | External source temporarily unavailable |
| `INTERNAL_ERROR` | 500 | Internal server error |

---

## 5. Rate Limits

| Plan | Requests/min | Requests/day | Max Results |
|------|--------------|--------------|-------------|
| Free | 10 | 500 | 100 |
| Basic | 60 | 5,000 | 200 |
| Pro | 300 | 50,000 | 500 |
| Enterprise | Custom | Custom | Custom |

---

## 6. Versioning

- API version included in URL path (`/v1/`, `/v2/`)
- New version release for breaking changes
- Previous versions supported for minimum 12 months

---

## 7. SDK Support

### Python SDK (planned)

```python
from lexiconarxiv import Client

client = Client(api_key="your_api_key")

# Search
results = client.search(
    query="instruction tuning Korean",
    year_from=2023,
    limit=100
)

for paper in results.papers:
    print(f"{paper.title} ({paper.year})")

# Export
bibtex = client.export(
    paper_ids=[p.id for p in results.papers[:10]],
    format="bibtex"
)
```

---

## 8. Graph Visualization API

Interactive citation graph exploration API with D3.js-compatible responses.

**Local Base URL**: `http://localhost:8000`

### 8.1 Quick Start

```bash
# Start the API server
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Open visualization UI
open http://localhost:8000

# API documentation
open http://localhost:8000/docs
```

### 8.2 Endpoints

#### GET /graph/health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "index_built": true,
  "storage_connected": true
}
```

---

#### GET /graph/stats

Overall citation graph statistics.

**Response**:
```json
{
  "total_papers": 150000,
  "total_real_papers": 120000,
  "total_stub_papers": 30000,
  "papers_with_refs": 95000,
  "papers_with_resolved_refs": 90000,
  "total_raw_refs": 2500000,
  "total_resolved_refs": 1800000,
  "resolution_coverage": 72.0,
  "papers_with_graph_metrics": 85000,
  "index_num_papers": 118000,
  "index_num_edges": 1800000,
  "index_memory_mb": 450.5
}
```

---

#### GET /graph/paper/{paper_id}

Get detailed information about a specific paper.

**Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `paper_id` | string | Qdrant point UUID |

**Response**:
```json
{
  "id": "dfc148fb-1efe-46d2-be20-2a963429404e",
  "title": "DEBERTA: DECODING-ENHANCED BERT WITH DISENTANGLED ATTENTION",
  "abstract": "Recent progress in pre-trained neural language models...",
  "venue": "International Conference on Learning Representations",
  "year": 2021,
  "doi": null,
  "citation_count": 922,
  "authors": ["Pengcheng He", "Xiaodong Liu", "Jianfeng Gao", "Weizhu Chen"],
  "is_core": true,
  "resolved_references": ["uuid-1", "uuid-2"],
  "cited_by": ["uuid-3", "uuid-4", "uuid-5"],
  "in_corpus_citation_count": 38,
  "reference_count": 2
}
```

---

#### GET /graph/subgraph/{paper_id}

Get N-hop neighborhood subgraph around a paper. Returns D3.js-compatible node-link format.

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `paper_id` | string | required | Center paper UUID |
| `hops` | int | 1 | Number of hops (1-3) |
| `direction` | string | "both" | Edge direction: `both`, `citing`, `cited` |

**Direction Options**:
- `both`: Follow both incoming and outgoing citations
- `citing`: Only papers that cite the center (incoming)
- `cited`: Only papers that the center cites (outgoing)

**Example Request**:
```
GET /graph/subgraph/dfc148fb-1efe-46d2-be20-2a963429404e?hops=2&direction=both
```

**Response** (D3.js node-link format):
```json
{
  "nodes": [
    {
      "id": "dfc148fb-1efe-46d2-be20-2a963429404e",
      "title": "DEBERTA: DECODING-ENHANCED BERT WITH DISENTANGLED ATTENTION",
      "year": 2021,
      "venue": "ICLR",
      "authors": ["Pengcheng He", "Xiaodong Liu"],
      "citation_count": 922,
      "doi": null,
      "is_center": true
    },
    {
      "id": "uuid-citing-paper",
      "title": "Paper that cites DeBERTa",
      "year": 2022,
      "venue": "ACL",
      "authors": ["Author Name"],
      "citation_count": 45,
      "doi": "10.18653/v1/2022.acl-long.123",
      "is_center": false
    }
  ],
  "links": [
    {
      "source": "uuid-citing-paper",
      "target": "dfc148fb-1efe-46d2-be20-2a963429404e"
    }
  ],
  "stats": {
    "num_nodes": 49,
    "num_edges": 49,
    "density": 0.020833,
    "center_paper_id": "dfc148fb-1efe-46d2-be20-2a963429404e",
    "hops": 2,
    "direction": "both"
  }
}
```

### 8.3 Visualization UI

The API includes an interactive D3.js visualization at the root URL (`/`).

**Features**:
- Force-directed graph layout
- Color-coded edges:
  - **Cyan**: Papers citing the center (incoming)
  - **Orange**: Papers cited by center (outgoing)
  - **Gray**: Other connections
- Node size proportional to citation count
- Node color indicates publication year
- Click any node to explore its neighborhood
- Hover for paper details (title, year, venue, authors)
- Zoom and pan support
- Adjustable hops (1-3) and direction

### 8.4 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                   │
├─────────────────────────────────────────────────────────┤
│  Lifespan: Pre-build ReverseCitationIndex at startup    │
│  (~10-30s for 150K nodes)                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ /graph/     │   │ /graph/      │   │ /graph/     │  │
│  │ health      │   │ stats        │   │ paper/{id}  │  │
│  └─────────────┘   └──────────────┘   └─────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ /graph/subgraph/{paper_id}?hops=N&direction=D   │   │
│  │                                                  │   │
│  │  → CitationGraphBuilder.build_subgraph()        │   │
│  │  → NetworkX DiGraph                             │   │
│  │  → D3.js node-link JSON                         │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Dependencies (GraphServices)                           │
│  ├── QdrantStorage (lazy)                              │
│  ├── ReverseCitationIndex (pre-built)                  │
│  └── CitationGraphBuilder (lazy)                       │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Research & Advanced Endpoints

### 9.1 POST /api/research

Deep research on a topic with combined scoring and trend analysis.

**Request**:
```json
{
  "topic": "retrieval augmented generation evaluation",
  "year_from": 2023,
  "limit": 50
}
```

**Response** includes:
- Ranked papers with combined scoring (relevance + citations + PageRank)
- Trend data: paper counts and citation velocity by year
- Key authors and venues for the topic

### 9.2 POST /api/search (retrieval options)

Extended search with configurable retrieval pipeline stages.

**Request**:
```json
{
  "query": "efficient transformer inference",
  "retrieval": {
    "hyde": true,
    "rag_fusion": false,
    "reranker": true,
    "mmr": true
  },
  "limit": 20
}
```

The `retrieval` object toggles individual pipeline stages. See [Search Pipeline - Advanced Retrieval](../pipelines/search.md#11-advanced-retrieval-pipeline) for stage details and presets.

### 9.3 GET /api/paper/{id}/similar

Returns pre-computed similar papers for a given paper ID.

**Response**:
```json
{
  "paper_id": "uuid-here",
  "similar": [
    {"id": "uuid-1", "title": "...", "score": 0.92},
    {"id": "uuid-2", "title": "...", "score": 0.88}
  ]
}
```

### 9.4 GET /api/dashboard

Returns corpus-level statistics for the dashboard UI: total papers, papers by venue/year/tier, enrichment coverage, and embedding progress.

### 9.5 GET /api/corpus-gaps

Returns the biggest citation-graph holes: `top_cited_missing` (the most-cited enriched stubs — papers the corpus references most but doesn't hold, each linked by DOI/arXiv/OpenAlex) and `top_missing_venues` (a venue tally over that set). Server-side `order_by` on the indexed `cited_by_count_internal` (no full scroll); 5-min cache, `?limit=N` (default 100), `?refresh=true`.

---

## 10. MCP Tools (Updated)

The MCP server exposes 8 tools as of `main` HEAD 2026-07-03. Every handler runs under an `asyncio.wait_for` **timeout budget** — 5s default, per-handler overrides for legitimately slow endpoints. See [`docs/reference/mcp-server.md`](../reference/mcp-server.md) for the full tool catalog with input schemas, response shapes, resolution ordering, and testing gotchas.

| Tool | Description | Timeout budget |
|------|-------------|----------------|
| `search_papers` | Hybrid dense+BM25 search with venue/year/tier/section filters | 5s |
| `get_paper` | Fetch one paper by UUID / DOI / arXiv ID / `10.48550/arxiv.<id>` variant | 5s |
| `get_citations` | References + cited-by graph for a paper | 5s |
| `get_similar_papers` | Typed similarity edges: same_method / same_task / same_result / method_transfer / overall | 5s |
| `get_corpus_stats` | Total-points + top-N venues (default 30, hard-capped at 200) with long-tail summary | 60s* |
| `expand_search` | Live arXiv + OpenAlex expansion with core/connected/external labeling | 20s |
| `research_topic` | Deep topic research: notable papers + trends + summary + combined scoring | 15s |
| `get_mcp_version` | Return `{git sha, startup timestamp, python version}` for stale-subprocess detection | 5s |

_\*`get_corpus_stats` runs a full-collection scroll in `get_venue_stats()`; the elevated budget is a known-perf ticket, not a target._

**On timeout**, the response is a diagnostic text error that names the failure mode ("query hits an unindexed payload field or a stalled backend"). Motivated by the 2026-07-03 incident where an unindexed `source_id` scroll silently blocked 60s per lookup — see [postmortem](../incidents/2026-07-03-mcp-search-endpoints-broken.md) Lesson 4.

### Cross-session staleness protocol

MCP subprocesses are per-Claude-session and have no hot reload. When session A commits a fix and session B's subprocess is still running the old code, session B calls `get_mcp_version`, compares to `git rev-parse --short HEAD` on disk, and reconnects (`/mcp reconnect lexiconarxiv`) if they differ. Reference: [`docs/reference/mcp-server.md#version-identity--stale-subprocess-detection`](../reference/mcp-server.md#version-identity--stale-subprocess-detection).

---

### 10.1 Performance Notes (Graph)

- **Startup**: ReverseCitationIndex pre-built (~10-30s for 150K nodes)
- **Query**: O(nodes in neighborhood), typically < 100ms
- **Max hops**: Limited to 3 to prevent result explosion
- **Memory**: ~450MB for 150K nodes with metadata
