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
