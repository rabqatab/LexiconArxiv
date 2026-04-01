# Enrichment Pipeline

## Overview

The enrichment pipeline fetches missing metadata (citations, abstracts) for papers collected from various sources. Papers from ACL Anthology, OpenReview, DBLP, and other sources often lack `referenced_works` and/or abstracts. The pipeline uses multiple external APIs to fill these gaps.

### Pipeline Summary

| Step | Command | Source API | Target |
|------|---------|-----------|--------|
| 1 | `enrich-1-refs-and-abstracts-by-doi-via-openalex` | OpenAlex | Papers with DOI, missing refs/abstracts |
| 2 | `enrich-2-refs-by-doi-via-crossref` | CrossRef | Papers with DOI, missing refs (ACM/Springer) |
| 3 | `enrich-3-refs-and-abstracts-by-title-via-openalex` | OpenAlex | Papers without DOI (title matching) |
| 4 | `enrich-4-refs-by-doi-via-s2` | Semantic Scholar | Fallback for remaining papers |
| 5 | `enrich-5-refs-by-pdf-via-grobid` | GROBID | PDF reference extraction |
| 6 | `enrich-6-abstracts-by-doi-via-openalex` | OpenAlex | Papers with DOI, missing abstracts |
| 7 | `enrich-8-metadata-by-stub-via-openalex` | OpenAlex | Stub paper metadata |
| 8 | `enrich-9-resolve-title-refs-via-openalex` | OpenAlex | Resolve TITLE:xxx references |
| 9 | `enrich-10-code-repos` | PWC / HuggingFace | Code repository URLs |
| 10 | `enrich-11-code-repos-via-grobid` | GROBID | GitHub URLs from paper PDFs |
| 11 | `enrich-12-code-repos-via-github` | GitHub API | GitHub search (arXiv ID + title) |

---

## 1. Unified Enrichment Architecture

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Unified Enrichment Pipeline                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Qdrant    │───▶│   Paper     │───▶│    OpenAlex API     │ │
│  │  (papers    │    │  Enricher   │    │  /works/doi:{doi}   │ │
│  │  missing    │    │ (parallel)  │    │                     │ │
│  │  data)      │    └──────┬──────┘    └──────────┬──────────┘ │
│  └─────────────┘           │                      │             │
│                            │  refs / abstract     │             │
│                            ▼                      ▼             │
│                    ┌─────────────┐    ┌─────────────────────┐  │
│                    │ Checkpoint  │    │   Update Qdrant     │  │
│                    │ (progress)  │    │   set_payload()     │  │
│                    └─────────────┘    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
src/core/enrichment/
├── __init__.py            # Package exports
├── base.py                # Base classes and mixins
├── openalex.py            # OpenAlex enricher (PaperEnricher)
├── crossref.py            # CrossRef enricher
├── semantic_scholar.py    # Semantic Scholar enricher
├── stub.py                # Stub paper enricher
├── pdf.py                 # PDF reference extraction via GROBID
├── code_repos.py          # Code repo enrichment (PWC/HuggingFace)
├── grobid_code_repos.py   # GitHub URL extraction from PDFs via GROBID
└── github_search.py       # GitHub API search for code repositories
```

### Class Hierarchy

```
BaseEnricher (ABC)
    ├── _client (httpx.AsyncClient)
    ├── _semaphore (concurrency control)
    ├── storage (QdrantStorage)
    ├── delay, max_concurrent
    └── __aenter__, __aexit__

OpenAlexMixin
    ├── _init_openalex(key_manager)     # Accepts OpenAlexKeyManager (or creates from env)
    ├── _get_openalex_params()          # Round-robin key rotation via key manager
    ├── _handle_api_key_exhaustion()    # Marks specific key exhausted, falls back when all exhausted
    ├── fetch_openalex_work(identifier, identifier_type)  # Max 3 retries on rate limit
    ├── parse_openalex_work(data)
    └── reconstruct_abstract(inverted_index)  [static]

CrossRefMixin
    ├── _init_crossref(email)
    ├── _get_crossref_headers()
    ├── fetch_crossref_work(doi, max_retries)
    └── parse_crossref_work(message)

PaperEnricher(BaseEnricher, OpenAlexMixin)
    ├── Enriches corpus papers with citations/abstracts
    └── Title matching: _normalize_title() + _titles_match() (SequenceMatcher ≥ 0.90)

StubEnricher(BaseEnricher, OpenAlexMixin, CrossRefMixin)
    └── Enriches stub papers, handles cross-reference deduplication

CrossRefEnricher(BaseEnricher, CrossRefMixin)
    └── Enriches papers using CrossRef as primary source

ReferenceResolver(OpenAlexMixin)
    └── Resolves arXiv IDs to DOIs, uses mixin for API key exhaustion fallback
```

### Shared Functionality

| Component | Provided By | Used By |
|-----------|-------------|---------|
| Async context management | `BaseEnricher` | All enrichers |
| Rate limiting (semaphore) | `BaseEnricher` | All enrichers |
| OpenAlex API fetching | `OpenAlexMixin` | `PaperEnricher`, `StubEnricher`, `ReferenceResolver` |
| OpenAlex API key fallback | `OpenAlexMixin` | `PaperEnricher`, `StubEnricher`, `ReferenceResolver` |
| OpenAlex response parsing | `OpenAlexMixin` | `PaperEnricher`, `StubEnricher` |
| Abstract reconstruction | `OpenAlexMixin` | `PaperEnricher`, `StubEnricher` |
| CrossRef API fetching | `CrossRefMixin` | `CrossRefEnricher`, `StubEnricher` |
| CrossRef response parsing | `CrossRefMixin` | `CrossRefEnricher`, `StubEnricher` |

### Parallel Processing

All enrichers support concurrent API calls via `--parallel N` using `asyncio.Semaphore`:

| Configuration | Recommended `--parallel` |
|---------------|-------------------------|
| With API key | 10 |
| With email only | 5 |
| No auth | 1 (sequential) |

---

## 2. OpenAlex Enrichment (Steps 1, 3, 6)

### Step 1: DOI-based Enrichment

Fetches citations and abstracts from OpenAlex for papers with DOIs.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --dry-run

# Run with parallel requests
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10

# With limit
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --limit 1000
```

### Step 3: Title-based Enrichment

For papers without DOIs, matches titles against OpenAlex using normalized `SequenceMatcher` similarity (threshold ≥ 0.90).

```bash
uv run python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --parallel 5
```

### Step 6: Abstract-only Enrichment

Fetches missing abstracts from OpenAlex for papers that already have refs but lack abstracts.

```bash
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --dry-run
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10
```

### Reset Title-enriched Papers

If title matching produces false positives, reset and re-run:

```bash
uv run python -m src.cli.core_collect reset-title-enriched --dry-run
uv run python -m src.cli.core_collect reset-title-enriched
```

### Coverage Impact

**Citations:**

| Metric | Before | After |
|--------|--------|-------|
| Papers with `referenced_works` | 19% (5,929) | ~55% (16,855) |
| ACL papers enrichable | 0% | 61% (7,754) |
| OpenReview papers enrichable | 0% | 27% (3,172) |

**Abstracts:**

| Metric | Before | After |
|--------|--------|-------|
| Papers with abstracts | ~92% | ~98% |
| DBLP papers with abstracts | 0% | ~95% |

### Source Gaps Addressed

| Source | Has Abstracts | Has Refs | Enrichment |
|--------|---------------|----------|------------|
| OpenAlex | Yes | Yes | N/A (primary source) |
| ACL Anthology | Yes | No | Steps 1, 3 |
| OpenReview | Yes | No | Steps 1, 3 |
| ACM DL | Yes | No | Steps 1, 2 |
| AAAI OJS | Yes | No | Steps 1, 3 |
| **DBLP** | **No** | **No** | Steps 1, 3, 6 |

### Implementation

- Module: `src/core/enrichment/openalex.py` (unified enricher with parallel support)
- Storage methods:
  - `get_papers_missing_references()`, `batch_update_referenced_works()`
  - `get_papers_missing_abstracts()`, `batch_update_abstracts()`
  - `get_papers_with_title_refs()` (for TITLE:xxx resolution)
  - `get_data_quality_stats()`
- Checkpoints:
  - `data/core/checkpoints/citation_enrichment.json`
  - `data/core/checkpoints/abstract_enrichment.json`

---

## 3. CrossRef Enrichment (Step 2)

### Why CrossRef?

CrossRef is the authoritative source for DOI metadata and provides excellent reference data for ACM and other publisher papers.

| Source | ACM Paper Success Rate | References Per Paper |
|--------|----------------------|---------------------|
| Semantic Scholar | ~0% (papers found, no refs) | - |
| OpenAlex | Partial | ~25 |
| **CrossRef** | **97%** | **33** |

CrossRef is particularly valuable for:
- **ACM Digital Library papers** - Blocked by Cloudflare (403) for direct access, but CrossRef has full metadata
- **Springer papers** - Similar access restrictions
- **Any DOI-registered paper** - CrossRef is the canonical DOI registry

### API Rate Limits

| Pool | Rate Limit | Access |
|------|------------|--------|
| Public | 50 req/sec | Anonymous |
| Polite | 50 req/sec | With `mailto` parameter (recommended) |

Set `CROSSREF_EMAIL` env var for polite pool access.

### Reference Format

CrossRef returns references in two formats:
1. **Structured** - With DOI, title, authors (resolvable)
2. **Unstructured** - Raw citation string (for later resolution)

Typical breakdown: ~67% of references have DOIs.

### Usage

```bash
# Basic enrichment
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref

# Preview
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --dry-run

# With limit and concurrency
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --limit 500 --parallel 20
```

### Coverage Impact

| Metric | Before CrossRef | After CrossRef |
|--------|-----------------|----------------|
| Papers with refs | 73.4% | ~88% |
| ACM papers with refs | ~0% | ~97% |

### Implementation

Module: `src/core/enrichment/crossref.py`

Features:
- DOI-based lookup via `https://api.crossref.org/works/{doi}`
- Polite pool access with mailto header
- Checkpoint-based resumption
- Automatic rate limit handling
- Reference format conversion (DOI → `doi:X`, unstructured → `title:X`)

---

## 4. Semantic Scholar Enrichment (Step 4)

### Overview

Semantic Scholar (S2) provides an alternative API for citation data, useful as a fallback for papers not enrichable via OpenAlex or CrossRef.

### API Keys (Recommended)

Get a free API key for ~30x faster processing:
1. Register at: https://www.semanticscholar.org/product/api#api-key
2. Set the environment variable:
   ```env
   # Single key (legacy, still works)
   S2_API_KEY=your_key_here

   # Multiple keys for round-robin rotation (recommended)
   S2_API_KEYS=key1,key2,key3
   ```

**Multi-key rotation:** When `S2_API_KEYS` is set (comma-separated), keys are rotated round-robin with per-key rate limiting. When one key hits a 429, it enters a cooldown while remaining keys continue. This multiplies effective throughput by the number of keys.

### Rate Limits

| Configuration | Requests/sec | Time for 10K papers |
|--------------|-------------|---------------------|
| Without API key | 0.3 | ~9 hours |
| With 1 API key | 1 | ~3 hours |
| With 3 API keys | ~3 | ~1 hour |

Rate limits are **auto-adjusted** based on API key presence.

### Usage

```bash
# DOI-based (auto-detects API key)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2

# Title-based search (for papers without DOI)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title

# Target specific venues
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title -v "NeurIPS 2024 poster"

# Prioritize recently collected papers (incremental enrichment)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --recent-days 30
```

### Implementation

Module: `src/core/enrichment/semantic_scholar.py`

Features:
- DOI-based lookup via `/graph/v1/paper/DOI:{doi}`
- Title-based search via `/graph/v1/paper/search`
- Automatic rate limit handling with retry
- Checkpoint-based resumption

---

## 5. PDF Reference Extraction (Step 5)

### Overview

Extract references from PDFs using GROBID for papers where API-based enrichment fails.

### Prerequisites

Start GROBID server:
```bash
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
```

### Usage

```bash
# Preview
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --dry-run

# Run (low concurrency recommended)
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel 2
```

### Implementation

Module: `src/core/enrichment/pdf.py`

---

## 6. Stub Paper Enrichment (Step 7)

### Overview

Stub papers are external references that don't exist in the corpus. Enrichment fetches metadata from OpenAlex/CrossRef and detects/merges duplicates.

### The Deduplication Problem

The same external paper can be referenced with different identifiers:
```
Paper A cites "Adam" via DOI:10.48550/arXiv.1412.6980
Paper B cites "Adam" via arXiv:1412.6980
Paper C cites "Adam" via W1522301498 (OpenAlex)
```

The enricher discovers all identifiers from OpenAlex, finds matching stubs, and merges them:
```
Before: 3 stubs × 5 citations each = 15 total (split)
After:  1 stub × 15 citations = accurate count
```

### Usage

```bash
# Enrich top 100 most-cited stubs
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex

# Filter by identifier type
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --type doi --limit 500

# Only highly-cited stubs (5+ citations)
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --min-citations 5

# Check results
uv run python -m src.cli.core_collect stub-stats
```

### Stub Schema After Enrichment

```json
{
  "is_stub": true,
  "identifier": "W1522301498",
  "identifier_type": "openalex",
  "title": "Adam: A Method for Stochastic Optimization",
  "year": 2014,
  "authors": ["Diederik P. Kingma", "Jimmy Ba"],
  "venue": "ICLR",
  "cited_by_count_internal": 15,
  "alternate_identifiers": {
    "doi": "10.48550/arxiv.1412.6980",
    "arxiv": "1412.6980"
  }
}
```

### Implementation

Module: `src/core/enrichment/stub.py`

---

## 7. Code Repository Enrichment (Steps 10, 11, 12)

### Overview

The code repository enrichment pipeline finds GitHub repositories associated with papers using three sequential strategies:

| Step | Source | Strategy | Hit Rate |
|------|--------|----------|----------|
| enrich-10 | PWC Archive + HuggingFace | arXiv ID + title lookup | ~13% |
| enrich-11 | GROBID Full-Text | GitHub URL extraction from PDFs | Varies |
| enrich-12 | GitHub API | arXiv ID in README + title search | Varies |

### Data Flow

```
Papers without code_repositories
       │
  enrich-10: PWC Archive + HuggingFace API
       │
  enrich-11: GROBID Full-Text → GitHub URL extraction
  (requires: pdf_url + GROBID server running)
       │
  enrich-12: GitHub API Search
  Tier A: arXiv ID in README.md (high precision)
  Tier B: Paper title search (validated)
```

### Step 10: PWC Archive + HuggingFace (Primary)

Looks up code repositories from Papers With Code (PWC) Archive and HuggingFace Papers API using arXiv IDs and paper titles.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-10-code-repos --dry-run

# Run
uv run python -m src.cli.core_collect enrich-10-code-repos --parallel 10
```

### Step 11: GROBID Full-Text Extraction

Downloads paper PDFs, processes full text via GROBID, and extracts GitHub URLs with section/context-based classification heuristics.

**GitHub URL Classification:**
- Blocklist (~40 well-known library repos) filters out common dependencies (pytorch/pytorch, tensorflow/tensorflow, etc.)
- Section-based scoring: +3 for own-code phrases, +2 for abstract/conclusion, -2 for references section
- URLs with score >= 2 are marked `is_official=True`

**Prerequisites:** GROBID server running (`docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0`)

```bash
# Preview
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --dry-run

# Run (low concurrency recommended for GROBID)
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --parallel 5
```

### Step 12: GitHub API Search

Two-tier GitHub API search for papers still missing code repositories:

- **Tier A**: Search for arXiv ID in README.md files (high precision, `is_official=True`)
- **Tier B**: Title search with validation heuristics (fork check, temporal check, title similarity >= 40%)

**Rate Limits:** 30 search req/min with `GITHUB_TOKEN`, 10/min without.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --dry-run

# Run
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --batch-size 50
```

### Repo Dict Structure

All code repo enrichers write the same format:
```json
{
    "url": "https://github.com/owner/repo",
    "is_official": true,
    "framework": null,
    "stars": null,
    "source": "pwc_archive|huggingface|grobid_fulltext|github_search_code|github_search_repo"
}
```

### Implementation

| Module | File |
|--------|------|
| PWC/HF Enricher | `src/core/enrichment/code_repos.py` |
| GROBID Extraction | `src/core/enrichment/grobid_code_repos.py` |
| GitHub Search | `src/core/enrichment/github_search.py` |

Checkpoints:
- `data/core/checkpoints/code_repo_enrichment.json`
- `data/core/checkpoints/grobid_code_repo_extraction.json`
- `data/core/checkpoints/github_search_enrichment.json`

---

## 8. Data Quality Dashboard

Monitor enrichment coverage with the data quality CLI command:

```bash
# Summary
uv run python -m src.cli.core_collect data-quality

# JSON output
uv run python -m src.cli.core_collect data-quality --json

# By venue breakdown
uv run python -m src.cli.core_collect data-quality --by-venue
```

### Example Output

```
=== Data Quality Report ===

Total papers: 30,841

=== By Source ===
Source          Papers    Has DOI   Has Abstract   Has Refs
──────────────────────────────────────────────────────────────
openalex        15,234    100.0%    98.5%          100.0%
acl_anthology   12,754     61.0%    99.2%            0.0%
openreview       1,523     85.0%    100.0%           0.0%
dblp             1,330     95.0%     0.0%            0.0%
──────────────────────────────────────────────────────────────

=== Coverage Summary ===
Metric              Count      Percent
──────────────────────────────────────
Papers with DOI     25,123     81.5%
Papers with abstract 28,456    92.3%
Papers with refs     5,929     19.2%

=== Enrichment Potential ===
Citation enrichment: 10,926 papers can be enriched (have DOI, no refs)
Abstract enrichment: 1,330 papers can be enriched (have DOI, no abstract)
```

### Implementation

- Storage method: `QdrantStorage.get_data_quality_stats()` in `src/core/storage/statistics.py`
- CLI command: `data-quality` in `src/cli/commands/quality.py`

---

## 9. Recommended Enrichment Pipeline Order

For maximum coverage, run enrichment sources in this order:

```bash
# 1. OpenAlex DOI lookup (primary source, highest quality)
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10

# 2. CrossRef (excellent for ACM/Springer papers - 97% success rate)
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel 10

# 3. OpenAlex title lookup (for papers without DOI)
uv run python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --parallel 5

# 4. Semantic Scholar fallback
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2

# 5. GROBID PDF extraction (for papers with accessible PDFs)
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid

# 6. Abstract enrichment (fill remaining gaps)
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10

# 7. Resolve references to internal IDs (with stub paper creation)
uv run python -m src.cli.core_collect resolve-refs

# 8. Build cited_by index
uv run python -m src.cli.core_collect build-cited-by

# 9. (Optional) Enrich stub papers with metadata
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --limit 1000

# 10. (Optional) Resolve TITLE:xxx references
uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --parallel 3

# 11. Code repository enrichment (PWC/HuggingFace)
uv run python -m src.cli.core_collect enrich-10-code-repos --parallel 10

# 12. GROBID code repo extraction (requires GROBID server)
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --parallel 5

# 13. GitHub API code repo search
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --batch-size 50
```

---

## 10. Checkpoint Management

Each enrichment step uses checkpoints for resumable processing:

```bash
uv run python -m src.cli.core_collect clear-enrich-1-checkpoint
uv run python -m src.cli.core_collect clear-enrich-2-checkpoint
uv run python -m src.cli.core_collect clear-enrich-3-checkpoint
uv run python -m src.cli.core_collect clear-enrich-4-checkpoint
uv run python -m src.cli.core_collect clear-enrich-5-checkpoint
uv run python -m src.cli.core_collect clear-enrich-6-checkpoint
uv run python -m src.cli.core_collect clear-enrich-9-checkpoint
uv run python -m src.cli.core_collect clear-enrich-10-checkpoint
uv run python -m src.cli.core_collect clear-enrich-11-checkpoint
uv run python -m src.cli.core_collect clear-enrich-12-checkpoint
uv run python -m src.cli.core_collect clear-keyword-checkpoint
```

Checkpoint files are stored in `data/core/checkpoints/`.

---

## 11. Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENALEX_API_KEYS` | Comma-separated OpenAlex API keys for round-robin rotation | No |
| `OPENALEX_EMAIL` | Email for OpenAlex polite pool fallback (10 req/sec) | Yes |
| `S2_API_KEYS` | Semantic Scholar API keys, comma-separated for round-robin rotation (legacy `S2_API_KEY` still works) | No |
| `CROSSREF_EMAIL` | Email for CrossRef polite pool | No |
| `GITHUB_TOKEN` | GitHub personal access token (30 req/min vs 10/min) | No |

---

## See Also

- [Data Collection Pipeline](./data_collection.md)
- [Keyword Extraction Pipeline](./keyword_extraction.md)
- [Abstract Labeling Pipeline](./abstract_labeling.md)
- [CLI Reference](../reference/cli.md)
