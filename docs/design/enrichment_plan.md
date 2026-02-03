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
| `docs/guides/crawling_howto.md` | **MODIFY** | Document new commands |
| `docs/design/data_collection.md` | **MODIFY** | Update architecture |

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
   - Update crawling_howto.md
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
