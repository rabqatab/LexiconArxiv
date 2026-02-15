# Enrichment Pipeline Enhancements Plan

## Overview

This document outlines the implementation plan for three enhancements to the data enrichment pipeline:

1. **Abstract Enrichment** - Fetch missing abstracts for DBLP papers
2. **Data Quality Dashboard** - CLI command for coverage statistics
3. **Parallel Enrichment** - Concurrent API calls for faster processing

---

## 1. Abstract Enrichment

### Problem

DBLP papers (~5,000) have no abstracts, reducing search quality.

| Source | Has Abstracts |
|--------|---------------|
| OpenAlex | Yes |
| ACL Anthology | Yes |
| OpenReview | Yes |
| ACM Open | Yes |
| AAAI OJS | Yes |
| **DBLP** | **No** |

### Solution

Fetch abstracts from OpenAlex by DOI (same pattern as citation enrichment).

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Abstract Enrichment Pipeline                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Qdrant    │───▶│  Enricher   │───▶│    OpenAlex API     │ │
│  │  (papers    │    │ (batch      │    │  /works/doi:{doi}   │ │
│  │  with DOI,  │    │  processor) │    │                     │ │
│  │  no abstract│    └──────┬──────┘    └──────────┬──────────┘ │
│  └─────────────┘           │                      │             │
│                            │    abstract          │             │
│                            ▼                      ▼             │
│                    ┌─────────────┐    ┌─────────────────────┐  │
│                    │ Checkpoint  │    │   Update Qdrant     │  │
│                    │ (progress)  │    │   set_payload()     │  │
│                    └─────────────┘    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation

#### Storage Methods (`src/core/storage.py`)

```python
def get_papers_missing_abstracts(
    self,
    has_doi: bool = True,
    limit: int = 100,
    offset: str | None = None,
) -> tuple[list[tuple[str, dict]], str | None]:
    """Get papers with DOI but empty/missing abstract."""

def update_abstract(self, point_id: str, abstract: str) -> bool:
    """Update abstract for a paper."""

def batch_update_abstracts(
    self, updates: list[tuple[str, str]]
) -> int:
    """Batch update abstracts for multiple papers."""
```

#### Enricher Class (`src/core/enricher.py`)

Refactor to unified enricher supporting both citations and abstracts:

```python
class PaperEnricher:
    """Unified enricher for citations and abstracts."""

    async def fetch_paper_data(self, doi: str) -> dict | None:
        """Fetch full paper data from OpenAlex."""

    async def enrich_citations(self, dry_run=False, limit=None):
        """Enrich papers with citation data."""

    async def enrich_abstracts(self, dry_run=False, limit=None):
        """Enrich papers with abstract data."""
```

#### CLI Commands (`src/cli/core_collect.py`)

```python
@cli.command("enrich-abstracts")
@click.option("--dry-run", is_flag=True)
@click.option("--limit", "-n", type=int)
def enrich_abstracts(dry_run, limit):
    """Enrich papers with abstracts from OpenAlex."""

@cli.command("clear-abstract-checkpoint")
def clear_abstract_checkpoint():
    """Clear abstract enrichment checkpoint."""
```

---

## 2. Data Quality Dashboard

### Problem

No easy way to see coverage gaps across the corpus.

### Solution

CLI command showing comprehensive statistics by source, venue, and data completeness.

### Output Format

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

#### Storage Methods (`src/core/storage.py`)

```python
def get_data_quality_stats(self) -> dict:
    """Get comprehensive data quality statistics."""
    return {
        "total": int,
        "by_source": {
            "source_name": {
                "count": int,
                "has_doi": int,
                "has_abstract": int,
                "has_refs": int,
            }
        },
        "enrichment_potential": {
            "citations": int,  # has DOI, no refs
            "abstracts": int,  # has DOI, no abstract
        }
    }
```

#### CLI Command (`src/cli/core_collect.py`)

```python
@cli.command("data-quality")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--by-venue", is_flag=True, help="Show breakdown by venue")
def data_quality(output_json, by_venue):
    """Show data quality statistics and coverage gaps."""
```

---

## 3. Parallel Enrichment

### Problem

Sequential enrichment with 0.1s delay = ~36K papers/hour. Full enrichment takes ~18 minutes.

### Solution

Use `asyncio.Semaphore` for controlled concurrent API calls while respecting rate limits.

### Design

```python
class PaperEnricher:
    def __init__(
        self,
        max_concurrent: int = 10,  # Concurrent requests
        delay: float = 0.01,       # Delay between requests
        ...
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def _fetch_with_limit(self, doi: str) -> dict | None:
        """Fetch with semaphore-controlled concurrency."""
        async with self._semaphore:
            result = await self.fetch_paper_data(doi)
            await asyncio.sleep(self.delay)
            return result

    async def enrich_batch_parallel(
        self,
        papers: list[tuple[str, dict]],
        progress: EnrichmentProgress,
    ) -> int:
        """Enrich batch with parallel API calls."""
        tasks = [
            self._fetch_with_limit(p[1].get("doi"))
            for p in papers
            if p[1].get("doi")
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Process results...
```

### Rate Limit Considerations

| Configuration | Max Requests | Recommended Concurrency |
|---------------|--------------|------------------------|
| With API key | 100K/day (~70/min) | 10 concurrent |
| With email | 10K/day (~7/min) | 5 concurrent |
| No auth | 1K/day | 1 (sequential) |

### CLI Options

```python
@cli.command("enrich-citations")
@click.option("--parallel", "-p", type=int, default=1,
              help="Number of concurrent requests (default: 1)")
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/core/enricher.py` | **CREATE** | Unified enricher (replaces citation_enricher.py) |
| `src/core/citation_enricher.py` | **DELETE** | Merged into enricher.py |
| `src/core/storage.py` | **MODIFY** | Add abstract and stats methods |
| `src/cli/core_collect.py` | **MODIFY** | Add new CLI commands |
| `docs/guides/crawling.md` | **MODIFY** | Document new commands |
| `docs/pipelines/data_collection.md` | **MODIFY** | Update architecture |

---

## Implementation Order

1. **Phase 1: Refactor to Unified Enricher**
   - Create `src/core/enricher.py` with `PaperEnricher` class
   - Support both citation and abstract enrichment
   - Add parallel processing with semaphore
   - Migrate existing citation enrichment logic

2. **Phase 2: Add Abstract Enrichment**
   - Add `get_papers_missing_abstracts()` to storage
   - Add `update_abstract()` and `batch_update_abstracts()` to storage
   - Add `enrich_abstracts()` method to enricher
   - Add CLI commands

3. **Phase 3: Add Data Quality Dashboard**
   - Add `get_data_quality_stats()` to storage
   - Add `data-quality` CLI command
   - Support JSON output and venue breakdown

4. **Phase 4: Update Documentation**
   - Update crawling.md
   - Update data_collection.md

---

## CLI Commands Summary

After implementation:

```bash
# Citation enrichment
uv run python -m src.cli.core_collect enrich-citations --dry-run
uv run python -m src.cli.core_collect enrich-citations --limit 1000 --parallel 10
uv run python -m src.cli.core_collect clear-enrichment-checkpoint

# Abstract enrichment
uv run python -m src.cli.core_collect enrich-abstracts --dry-run
uv run python -m src.cli.core_collect enrich-abstracts --limit 1000 --parallel 10
uv run python -m src.cli.core_collect clear-abstract-checkpoint

# Data quality
uv run python -m src.cli.core_collect data-quality
uv run python -m src.cli.core_collect data-quality --json
uv run python -m src.cli.core_collect data-quality --by-venue
```

---

## Verification Steps

### 1. Test Data Quality Command
```bash
uv run python -m src.cli.core_collect data-quality
```

### 2. Test Abstract Enrichment (dry run)
```bash
uv run python -m src.cli.core_collect enrich-abstracts --dry-run
```

### 3. Test Parallel Citation Enrichment
```bash
uv run python -m src.cli.core_collect enrich-citations --limit 100 --parallel 5
```

### 4. Verify Enrichment Results
```bash
uv run python -c "
from src.core.storage import QdrantStorage
storage = QdrantStorage()
stats = storage.get_data_quality_stats()
print(f'Papers with abstracts: {stats[\"by_source\"]}')
"
```

---

---

## 4. Keyword Extraction

### Problem

Papers lack searchable keywords/acronyms, making exact paper retrieval difficult (e.g., "give me the HyDE paper").

### Solution

LLM-first extraction pipeline with regex + KeyBERT as fallback:

1. **LLM Extraction** (primary): Extract structured keywords via Gemini API or local Ollama
2. **Fallback**: Regex + KeyBERT (only when LLM is unavailable or fails)
3. **LLM Judge** (optional): Validate and filter keywords for relevance

### Architecture

```
LLM Extraction ──success──▶ Normalize → Judge → Qdrant
   (primary)                              (opt)
       │ failure
       ▼
Regex + KeyBERT (fallback)
```

### CLI Commands

```bash
# LLM-first pipeline with Gemini + judge (recommended)
uv run python -m src.cli.core_collect extract-keywords --llm --judge

# LLM-first with local Ollama
uv run python -m src.cli.core_collect extract-keywords --llm --judge --llm-backend ollama

# Fallback only: regex + KeyBERT (no LLM)
uv run python -m src.cli.core_collect extract-keywords

# Regex only (faster)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Preview
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Statistics
uv run python -m src.cli.core_collect keyword-stats
```

See [Keyword Extraction Design](./keyword_extraction.md) for full details.

---

## Implementation Status (Feb 2026)

All enrichment pipeline enhancements have been implemented:

| Feature | Status | Module |
|---------|--------|--------|
| Abstract Enrichment | ✅ Complete | `src/core/enrichment/openalex.py` |
| Data Quality Dashboard | ✅ Complete | `src/cli/core_collect.py` (`data-quality`) |
| Parallel Enrichment | ✅ Complete | `--parallel` flag on enrichment commands |
| Citation Enrichment (DOI) | ✅ Complete | `enrich-citations` command |
| Citation Enrichment (Title) | ✅ Complete | `enrich-citations-by-title` command |
| PDF Reference Extraction | ✅ Complete | `extract-pdf-refs` (requires GROBID) |
| CrossRef Enrichment | ✅ Complete | `enrich-crossref` command |

### Additional Enrichment (Added Feb 2026)

| Feature | Status | Description |
|---------|--------|-------------|
| Title-based OpenAlex lookup | ✅ Complete | For papers without DOI (SequenceMatcher ≥ 0.90) |
| PDF extraction via GROBID | ✅ Complete | Extracts refs from PDF for papers with no DOI match |
| GROBID ARM64 support | ✅ Complete | Native build for Apple Silicon |
| CrossRef enrichment | ✅ Complete | 97% success rate for ACM papers (vs 0% for S2) |

### CLI Commands

```bash
# Multi-source enrichment pipeline (recommended order)
uv run python -m src.cli.core_collect enrich-citations --parallel 10       # Step 1: OpenAlex DOI lookup
uv run python -m src.cli.core_collect enrich-crossref --parallel 10        # Step 2: CrossRef (ACM/Springer)
uv run python -m src.cli.core_collect enrich-citations-by-title --parallel 5  # Step 3: Title lookup
uv run python -m src.cli.core_collect extract-pdf-refs                      # Step 4: PDF extraction
uv run python -m src.cli.core_collect enrich-abstracts --parallel 10        # Step 5: Abstracts

# Semantic Scholar fallback (alternative for papers not in CrossRef)
uv run python -m src.cli.core_collect enrich-s2                            # DOI-based
uv run python -m src.cli.core_collect enrich-s2 --by-title                 # Title-based

# CrossRef enrichment (excellent for ACM papers - 97% success rate)
uv run python -m src.cli.core_collect enrich-crossref                      # DOI-based
uv run python -m src.cli.core_collect enrich-crossref --dry-run            # Preview only

# Data quality
uv run python -m src.cli.core_collect data-quality

# Reset title-enriched papers (if false positives detected)
uv run python -m src.cli.core_collect reset-title-enriched --dry-run
uv run python -m src.cli.core_collect reset-title-enriched
```

---

## 5. Semantic Scholar Enrichment

### Overview

Semantic Scholar (S2) provides an alternative API for citation data, particularly useful for:
- Papers from sources that block PDF downloads (e.g., ACM Digital Library)
- Papers not indexed by OpenAlex
- ML/AI conference papers (NeurIPS, ICML, ICLR, ACL)

### API Key (Recommended)

Get a free API key for ~30x faster processing:

1. Register at: https://www.semanticscholar.org/product/api#api-key
2. Set the environment variable:
   ```bash
   export S2_API_KEY=your_key_here
   ```

### Rate Limits

| Configuration | Requests/sec | Concurrent | Time for 10K papers |
|--------------|-------------|------------|---------------------|
| Without API key | 0.3 | 1 | ~9 hours |
| With API key | 1 | 1 | ~3 hours |

S2 API limit with key: **1 request per second** (cumulative across all endpoints).

Rate limits are **auto-adjusted** based on API key presence.

### Usage

```bash
# Basic enrichment (auto-detects API key)
uv run python -m src.cli.core_collect enrich-s2

# With explicit API key
S2_API_KEY=your_key uv run python -m src.cli.core_collect enrich-s2

# Title-based search (for papers without DOI)
uv run python -m src.cli.core_collect enrich-s2 --by-title

# Override rate limits manually
uv run python -m src.cli.core_collect enrich-s2 --delay 0.5 --parallel 3
```

### Implementation

The S2 enricher (`src/core/enrichment/semantic_scholar.py`) supports:
- DOI-based lookup via `/graph/v1/paper/DOI:{doi}`
- Title-based search via `/graph/v1/paper/search`
- Automatic rate limit handling with retry
- Checkpoint-based resumption

---

## 6. CrossRef Enrichment

### Overview

CrossRef is the authoritative source for DOI metadata and provides excellent reference data for ACM and other publisher papers. It serves as a primary enrichment source where other APIs (S2, OpenAlex) fail.

### Why CrossRef?

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

CrossRef provides generous rate limits:

| Pool | Rate Limit | Access |
|------|------------|--------|
| Public | 50 req/sec | Anonymous |
| Polite | 50 req/sec | With `mailto` parameter (recommended) |

To access the polite pool (better reliability), include your email:
```bash
export CROSSREF_EMAIL=your@email.com
```

### Reference Format

CrossRef returns references in two formats:
1. **Structured** - With DOI, title, authors (resolvable)
2. **Unstructured** - Raw citation string (for later resolution)

Typical breakdown: ~67% of references have DOIs.

### Usage

```bash
# Basic enrichment (targets papers with DOI but no refs)
uv run python -m src.cli.core_collect enrich-crossref

# Dry run to see what would be enriched
uv run python -m src.cli.core_collect enrich-crossref --dry-run

# Limit number of papers to process
uv run python -m src.cli.core_collect enrich-crossref --limit 500

# Adjust concurrent requests (default: 10)
uv run python -m src.cli.core_collect enrich-crossref --parallel 20

# Clear checkpoint to restart from beginning
uv run python -m src.cli.core_collect clear-crossref-checkpoint
```

### Implementation

The CrossRef enricher (`src/core/enrichment/crossref.py`) provides:

```python
class CrossRefEnricher:
    """Enrich papers with citation data from CrossRef."""

    async def enrich_by_doi(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> CrossRefEnrichmentProgress:
        """Enrich papers that have DOI but no referenced_works."""
```

Features:
- DOI-based lookup via `https://api.crossref.org/works/{doi}`
- Polite pool access with mailto header
- Checkpoint-based resumption
- Automatic rate limit handling
- Reference format conversion (DOI → `doi:X`, unstructured → `title:X`)

### Enrichment Pipeline Order

For maximum coverage, run enrichment sources in this order:

```bash
# 1. OpenAlex (primary source, highest quality)
uv run python -m src.cli.core_collect enrich-citations --parallel 10

# 2. CrossRef (excellent for ACM/Springer papers)
uv run python -m src.cli.core_collect enrich-crossref --parallel 10

# 3. Semantic Scholar (fallback for remaining papers)
uv run python -m src.cli.core_collect enrich-s2

# 4. GROBID PDF extraction (for papers with accessible PDFs)
uv run python -m src.cli.core_collect extract-pdf-refs

# 5. Resolve references to internal IDs (with stub paper creation)
uv run python -m src.cli.core_collect resolve-refs

# 6. Build cited_by index
uv run python -m src.cli.core_collect build-cited-by

# 7. (Optional) Enrich stub papers with metadata
uv run python -m src.cli.core_collect enrich-stubs --limit 1000

# 8. (Optional) Check most-cited external papers
uv run python -m src.cli.core_collect stub-stats
```

### Expected Coverage Impact

Based on PoC testing (Feb 2026):

| Metric | Before CrossRef | After CrossRef |
|--------|-----------------|----------------|
| Papers with refs | 73.4% | ~88% |
| ACM papers with refs | ~0% | ~97% |

CrossRef can enrich approximately 1,360 of the 1,401 ACM papers that were previously unreachable.

---

## 7. Stub Paper Enrichment & Deduplication

### Overview

Stub papers are external references that don't exist in the corpus. During enrichment, we:
1. Fetch metadata (title, authors, year, venue, abstract) from OpenAlex/CrossRef
2. **Detect and merge duplicates** when the same paper is referenced with different identifiers

### The Deduplication Problem

The same external paper can be referenced with different identifiers:
```
Paper A cites "Adam" via DOI:10.48550/arXiv.1412.6980
Paper B cites "Adam" via arXiv:1412.6980
Paper C cites "Adam" via W1522301498 (OpenAlex)
```

Without deduplication, these create 3 separate stubs with split citation counts.

### Cross-Reference Merge

When enriching a stub, we discover all its identifiers from OpenAlex:

```python
# OpenAlex returns multiple identifiers for the same paper
{
    "doi": "10.48550/arXiv.1412.6980",
    "arxiv_id": "1412.6980",
    "openalex_id": "W1522301498"
}
```

The enricher then:
1. Checks if stubs exist with any of these identifiers
2. If found, merges the current stub into the existing one
3. Combines `cited_by` lists and stores all identifiers

### Result

```
Before: 3 stubs × 5 citations each = 15 total (split)
After:  1 stub × 15 citations = accurate count
```

### CLI Commands

```bash
# Enrich stubs with automatic deduplication
uv run python -m src.cli.core_collect enrich-stubs --limit 1000

# Filter by identifier type
uv run python -m src.cli.core_collect enrich-stubs --type doi --limit 500
uv run python -m src.cli.core_collect enrich-stubs --type arxiv --limit 500

# Only enrich highly-cited stubs
uv run python -m src.cli.core_collect enrich-stubs --min-citations 5

# Check results
uv run python -m src.cli.core_collect stub-stats
```

### Output Example

```
Stub Enrichment Results:
  Processed:    100
  Enriched:     45
  Merged:       12    ← Duplicates detected and merged
  Not found:    43
  Errors:       0
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

---

## 8. Enrichment Architecture

### Overview

The enrichment module uses a shared base class architecture to reduce code duplication and standardize API interactions.

### Module Structure

```
src/core/enrichment/
├── __init__.py          # Package exports
├── base.py              # Base classes and mixins (NEW)
├── openalex.py          # OpenAlex enricher (PaperEnricher)
├── crossref.py          # CrossRef enricher
├── semantic_scholar.py  # Semantic Scholar enricher
├── stub.py              # Stub paper enricher
└── pdf.py               # PDF reference extraction
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

### Usage Example

```python
from src.core.enrichment import StubEnricher

async with StubEnricher(email="you@example.com") as enricher:
    # Uses OpenAlexMixin methods
    data = await enricher.fetch_openalex_work("10.1234/paper", "doi")
    if data:
        metadata = enricher.parse_openalex_work(data)
        print(metadata["title"])
    
    # Uses CrossRefMixin methods (fallback)
    data = await enricher.fetch_crossref_work("10.1234/paper")
    if data:
        metadata = enricher.parse_crossref_work(data)
```

### Benefits

1. **No code duplication** - OpenAlex/CrossRef fetching logic is centralized
2. **Consistent error handling** - Rate limiting and retries in one place
3. **Easy to extend** - New enrichers can use mixins for API access
4. **Maintainability** - Changes to API handling propagate to all enrichers
