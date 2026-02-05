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
python -m src.cli.core_collect enrich-citations --dry-run
python -m src.cli.core_collect enrich-citations --limit 1000 --parallel 10
python -m src.cli.core_collect clear-enrichment-checkpoint

# Abstract enrichment
python -m src.cli.core_collect enrich-abstracts --dry-run
python -m src.cli.core_collect enrich-abstracts --limit 1000 --parallel 10
python -m src.cli.core_collect clear-abstract-checkpoint

# Data quality
python -m src.cli.core_collect data-quality
python -m src.cli.core_collect data-quality --json
python -m src.cli.core_collect data-quality --by-venue
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

## 4. Keyword Extraction (NEW)

### Problem

Papers lack searchable keywords/acronyms, making exact paper retrieval difficult (e.g., "give me the HyDE paper").

### Solution

Two-phase extraction pipeline:

1. **Regex-based Acronym Extraction**: Extract explicit acronyms from titles/abstracts
2. **KeyBERT Semantic Extraction**: Extract semantic keywords from abstracts

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 Keyword Extraction Pipeline                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Qdrant    │───▶│  Phase 1    │───▶│     Phase 2         │ │
│  │  (papers)   │    │  Regex      │    │     KeyBERT         │ │
│  └─────────────┘    │  Extraction │    │     Extraction      │ │
│                     └──────┬──────┘    └──────────┬──────────┘ │
│                            │                      │             │
│                            ▼                      ▼             │
│                     ┌─────────────────────────────────────┐     │
│                     │      Filter & Merge Keywords        │     │
│                     └──────────────────┬──────────────────┘     │
│                                        │                        │
│                                        ▼                        │
│                              ┌─────────────────┐                │
│                              │  Update Qdrant  │                │
│                              │   (keywords)    │                │
│                              └─────────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

### CLI Commands

```bash
# Keyword extraction
python -m src.cli.core_collect extract-keywords              # Full extraction
python -m src.cli.core_collect extract-keywords --dry-run    # Preview
python -m src.cli.core_collect extract-keywords --no-keybert # Regex only

# Statistics
python -m src.cli.core_collect keyword-stats
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

### Additional Enrichment (Added Feb 2026)

| Feature | Status | Description |
|---------|--------|-------------|
| Title-based OpenAlex lookup | ✅ Complete | For papers without DOI |
| PDF extraction via GROBID | ✅ Complete | Extracts refs from PDF for papers with no DOI match |
| GROBID ARM64 support | ✅ Complete | Native build for Apple Silicon |

### CLI Commands

```bash
# 4-step enrichment pipeline
python -m src.cli.core_collect enrich-citations --parallel 10       # Step 1: DOI lookup
python -m src.cli.core_collect enrich-citations-by-title --parallel 5  # Step 2: Title lookup
python -m src.cli.core_collect extract-pdf-refs                      # Step 3: PDF extraction
python -m src.cli.core_collect enrich-abstracts --parallel 10        # Step 4: Abstracts

# Semantic Scholar fallback (for ACM and other blocked sources)
python -m src.cli.core_collect enrich-s2                            # DOI-based
python -m src.cli.core_collect enrich-s2 --by-title                 # Title-based

# Data quality
python -m src.cli.core_collect data-quality
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
python -m src.cli.core_collect enrich-s2

# With explicit API key
S2_API_KEY=your_key python -m src.cli.core_collect enrich-s2

# Title-based search (for papers without DOI)
python -m src.cli.core_collect enrich-s2 --by-title

# Override rate limits manually
python -m src.cli.core_collect enrich-s2 --delay 0.5 --parallel 3
```

### Implementation

The S2 enricher (`src/core/enrichment/semantic_scholar.py`) supports:
- DOI-based lookup via `/graph/v1/paper/DOI:{doi}`
- Title-based search via `/graph/v1/paper/search`
- Automatic rate limit handling with retry
- Checkpoint-based resumption
