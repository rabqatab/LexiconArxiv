# Core Corpus Crawling HOWTO

This guide explains how to collect papers for the LexiconArxiv core corpus from multiple sources: OpenAlex, ACL Anthology, DBLP, OpenReview, ACM Digital Library, and AAAI OJS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Data Sources](#data-sources)
- [CLI Commands Reference](#cli-commands-reference)
- [Collection Strategies](#collection-strategies)
- [Incremental Updates (Crontab)](#incremental-updates-crontab)
- [Deduplication](#deduplication)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### 1. Environment Setup

Ensure your `.env` file is configured:

```env
OPENALEX_EMAIL=your-email@example.com  # Required for polite pool (10 req/sec)
OPENALEX_API_KEYS=key1,key2,key3       # Optional, comma-separated API keys
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=                         # Optional, for cloud Qdrant
```

### Multiple OpenAlex API Keys

To distribute load across multiple OpenAlex API keys, use comma-separated values:

```env
OPENALEX_API_KEYS=key1,key2,key3
OPENALEX_EMAIL=your-email@example.com
```

Keys are rotated round-robin across requests. When a key is exhausted (HTTP 429),
it enters a 5-minute cooldown while remaining keys continue serving requests.
When ALL keys are exhausted, the system falls back to the email-based polite pool.

| Configuration | Effective Daily Budget | Recommended `--parallel` |
|---|---|---|
| 1 API key | 100K credits | `--parallel 10` |
| 3 API keys | 300K credits | `--parallel 10` |
| Email only | ~10K/day | `--parallel 5` |

The legacy `OPENALEX_API_KEY` (single key) still works and is treated as a one-key pool.

### 2. Start Qdrant

```bash
# Using Docker
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant

# Or using docker-compose if configured
docker-compose up -d qdrant
```

### 3. Initialize Storage

```bash
uv run python -m src.cli.core_collect init-storage
```

---

## Quick Start

### Count Papers First (Recommended)

Before starting a full collection, check how many papers you'll be collecting:

```bash
# Count all papers from all OpenAlex venues (2020-present)
uv run python -m src.cli.core_collect collect --all --count-only

# Count for specific year range
uv run python -m src.cli.core_collect collect --all --count-only --since-year 2022
```

This shows:
- Paper count per venue
- Total count
- Estimated collection time

### Full Collection

```bash
# Collect from all sources (OpenAlex + ACL + DBLP + OpenReview + ACM + AAAI)
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020
```

---

## Data Sources

### OpenAlex (Primary)

**Best for:** ML/AI conferences and journals with rich metadata.

| Feature | Details |
|---------|---------|
| Coverage | 27 configured venues (Tier 0/1/2) |
| Metadata | Abstracts, citations, concepts, authors with affiliations |
| Rate Limit | 10 req/sec with email (polite pool) |
| Papers | ~100,000-150,000 (2020-present) |

**Venues included:**
- **Tier 0:** NeurIPS, ICML, ICLR, AAAI, IJCAI, ACL, EMNLP, SIGIR, KDD, JMLR, WWW
- **Tier 1:** NAACL, EACL, COLING, Findings, TACL, TOIS, ESWA, WSDM, CIKM, ICDM, ECIR, CoNLL, LREC, RecSys
- **Tier 2:** AILaw, ICAIL, JURIX

### ACL Anthology (NLP Focus)

**Best for:** NLP papers with complete proceedings coverage.

| Feature | Details |
|---------|---------|
| Coverage | 9 main NLP venues + 90+ workshops |
| Metadata | Abstracts, authors, PDF links |
| Rate Limit | GitHub raw files (generous) |
| Papers | ~20,000 main + ~10,000 workshops (2020-present) |

**Main Venues:**
- **Tier 0:** ACL, EMNLP
- **Tier 1:** NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC

**Workshops (Tier 2):**
- BioNLP, Clinical NLP, ArgMining, SemEval, and 90+ more
- Dynamically collected from ACL Anthology XML files
- All workshops co-located with main conferences

```bash
# List ACL venues
uv run python -m src.cli.core_collect list-acl-venues
```

### DBLP (IR/Legal Focus)

**Best for:** IR and Legal AI venues with poor OpenAlex coverage.

| Feature | Details |
|---------|---------|
| Coverage | 6 venues |
| Metadata | Authors, venue, year (NO abstracts) |
| Rate Limit | 1 req/sec (polite) |
| Papers | ~5,000 (2020-present) |

**Venues:**
- **Tier 1:** RecSys, ECIR, CIKM, WSDM
- **Tier 2:** ICAIL, JURIX

```bash
# List DBLP venues
uv run python -m src.cli.core_collect list-dblp-venues
```

### OpenReview (ML Venues - High Coverage)

**Best for:** ICLR, NeurIPS, ICML with complete paper metadata and reviews.

| Feature | Details |
|---------|---------|
| Coverage | ICLR (2013+), NeurIPS (2019+), ICML (2023+) |
| Metadata | Abstracts, authors, reviews, decisions |
| Rate Limit | 1 req/sec (unauthenticated) |
| Papers | ~15,000 accepted (2020-present) |

**API Versions:**
- **API v1** (`api.openreview.net`): ICLR 2013-2023, NeurIPS 2019-2022
- **API v2** (`api2.openreview.net`): ICLR 2024+, NeurIPS 2023+, ICML 2023+

The collector automatically selects the correct API version based on venue and year.

**Note:** By default, only **accepted papers** are collected. Use `--include-rejected` to include all submissions.

```bash
# List OpenReview venues
uv run python -m src.cli.core_collect list-openreview-venues

# Collect from specific venue (accepted papers only)
uv run python -m src.cli.core_collect collect-openreview --venue iclr --since-year 2020

# Include rejected/withdrawn submissions
uv run python -m src.cli.core_collect collect-openreview --venue iclr --include-rejected

# Collect all ML venues
uv run python -m src.cli.core_collect collect-openreview --all
```

### ACM Digital Library (Now Open Access)

**Best for:** ACM conferences (KDD, SIGIR, WWW, etc.) - fully open since Jan 2026.

| Feature | Details |
|---------|---------|
| Coverage | KDD, SIGIR, WWW, RecSys, CIKM, WSDM |
| Metadata | Full abstracts (via DOI access) |
| Rate Limit | 0.5 req/sec (web scraping) |
| Papers | ~10,000 (2020-present) |

```bash
# List ACM venues
uv run python -m src.cli.core_collect list-acm-venues

# Collect from specific venue
uv run python -m src.cli.core_collect collect-acm --venue kdd --since-year 2020

# Collect all ACM venues
uv run python -m src.cli.core_collect collect-acm --all
```

### AAAI OJS (AI Conference)

**Best for:** AAAI main conference papers (2020-2023). AAAI 2024+ uses OpenReview.

| Feature | Details |
|---------|---------|
| Coverage | AAAI, ICWSM |
| Metadata | Full abstracts, PDF links |
| Rate Limit | 1 req/sec |
| Papers | ~8,000 (2020-2023) |

```bash
# List AAAI venues
uv run python -m src.cli.core_collect list-aaai-venues

# Collect AAAI papers
uv run python -m src.cli.core_collect collect-aaai --since-year 2020
```

---

## CLI Commands Reference

### OpenAlex Collection

```bash
# Collect from a specific venue
uv run python -m src.cli.core_collect collect --venue neurips --since-year 2020

# Collect from a tier
uv run python -m src.cli.core_collect collect --tier 0 --since-year 2020

# Collect all venues
uv run python -m src.cli.core_collect collect --all --since-year 2020

# Count only (dry run)
uv run python -m src.cli.core_collect collect --all --count-only
```

### ACL Anthology Collection

```bash
# Collect from a specific venue
uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2020

# Collect all ACL main venues (no workshops)
uv run python -m src.cli.core_collect collect-acl --all

# Collect all ACL venues including workshops
uv run python -m src.cli.core_collect collect-acl --all --include-workshops

# Collect only workshop papers
uv run python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024
```

### DBLP Collection

```bash
# Collect from a specific venue
uv run python -m src.cli.core_collect collect-dblp --venue icail --since-year 2020

# Collect all DBLP venues
uv run python -m src.cli.core_collect collect-dblp --all
```

### OpenReview Collection

```bash
# Collect from a specific venue
uv run python -m src.cli.core_collect collect-openreview --venue iclr --since-year 2020

# Collect all OpenReview venues
uv run python -m src.cli.core_collect collect-openreview --all
```

### ACM Collection

```bash
# Collect from a specific venue
uv run python -m src.cli.core_collect collect-acm --venue kdd --since-year 2020

# Collect all ACM venues
uv run python -m src.cli.core_collect collect-acm --all

# Fast collection without abstracts
uv run python -m src.cli.core_collect collect-acm --venue www --no-abstracts
```

### AAAI OJS Collection

```bash
# Collect from AAAI
uv run python -m src.cli.core_collect collect-aaai --venue aaai --since-year 2020

# Collect all AAAI venues
uv run python -m src.cli.core_collect collect-aaai --all
```

### Multi-Source Collection

```bash
# Collect from all sources
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# Include ACL workshop papers
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Skip specific sources (if already collected)
uv run python -m src.cli.core_collect collect-all-sources --skip-openalex
uv run python -m src.cli.core_collect collect-all-sources --skip-acl --skip-dblp

# Collect only new sources (OpenReview, ACM, AAAI)
uv run python -m src.cli.core_collect collect-all-sources --skip-openalex --skip-acl --skip-dblp
```

### Status & Management

```bash
# Check collection status
uv run python -m src.cli.core_collect status

# List all configured venues
uv run python -m src.cli.core_collect list-venues

# Clear checkpoint (reset progress)
uv run python -m src.cli.core_collect clear-checkpoint
```

---

## Collection Strategies

### Strategy 1: Full Collection (Recommended for First Run)

Best for initial corpus building:

```bash
# Step 1: Check paper counts
uv run python -m src.cli.core_collect collect --all --count-only --since-year 2020

# Step 2: Collect from all sources
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020
```

**Order:** OpenAlex → ACL Anthology → DBLP

This order is important because:
1. OpenAlex has the richest metadata
2. Duplicates from ACL/DBLP are skipped (OpenAlex version preserved)

### Strategy 2: Source-by-Source (For Rate Limit Concerns)

If you're worried about rate limits:

```bash
# Day 1: ACL Anthology (fastest, no strict limits)
uv run python -m src.cli.core_collect collect-acl --all --since-year 2020

# Day 2: DBLP (slow but small)
uv run python -m src.cli.core_collect collect-dblp --all --since-year 2020

# Day 3+: OpenAlex (largest, with checkpoints)
uv run python -m src.cli.core_collect collect --all --since-year 2020
```

**Note:** This order means ACL/DBLP versions are kept when duplicates exist. OpenAlex versions are skipped.

### Strategy 3: Tier-Based Collection

For prioritizing top venues:

```bash
# Tier 0 first (most important)
uv run python -m src.cli.core_collect collect --tier 0 --since-year 2020

# Then Tier 1
uv run python -m src.cli.core_collect collect --tier 1 --since-year 2020
```

---

## Incremental Updates (Crontab)

For keeping the corpus up-to-date after initial collection.

### Daily Incremental Command

```bash
# Papers updated in last 24 hours
uv run python -m src.cli.core_collect collect-incremental

# Papers updated in last 7 days (weekly catch-up)
uv run python -m src.cli.core_collect collect-incremental --days 7

# Only specific source
uv run python -m src.cli.core_collect collect-incremental --source openalex
```

### Crontab Setup

Edit crontab:
```bash
crontab -e
```

Add daily job (runs at 2 AM):
```cron
0 2 * * * cd /path/to/LexiconArxiv && /path/to/uv run python -m src.cli.core_collect collect-incremental >> /var/log/lexicon_cron.log 2>&1
```

Or with virtual environment:
```cron
0 2 * * * cd /path/to/LexiconArxiv && .venv/bin/uv run python -m src.cli.core_collect collect-incremental >> /var/log/lexicon_cron.log 2>&1
```

### How Incremental Works

| Source | Method |
|--------|--------|
| OpenAlex | Uses `from_updated_date` API filter |
| ACL Anthology | Re-checks current year XML files |
| DBLP | Re-checks current year, deduplication handles existing |
| OpenReview | Re-checks current year venues |
| ACM | Re-checks current year, deduplication handles existing |
| AAAI | Re-checks current year issues |

---

## Deduplication

Papers are deduplicated across all sources using:

1. **DOI** (exact match, highest confidence)
2. **OpenAlex ID** (exact match)
3. **ACL ID** (exact match)
4. **Title + Year** (normalized, 95% confidence)

### Source Priority

When the same paper exists in multiple sources, the **first collected version is kept**. Sources are prioritized as follows:

| Priority | Source | Reason |
|----------|--------|--------|
| 1 | OpenAlex | Richest metadata (abstracts, concepts, citations) |
| 2 | OpenReview | Has reviews and decisions |
| 3 | ACL Anthology | Good abstracts, PDF links |
| 4 | ACM DL | Good abstracts (now open access) |
| 5 | DBLP | Basic metadata only, no abstracts |
| 6 | AAAI OJS | Basic metadata |
| 7 | arXiv | Preprint source |
| 8 | Semantic Scholar | Backup source |

**Recommendation:** Always collect OpenAlex first if you want the best metadata.

### Cross-Source Deduplication

When using `collect-all-sources`, papers are deduplicated across all sources automatically using a shared deduplicator. The first source to add a paper "wins" - subsequent sources will skip duplicates.

**Source collection order (determines which version is kept):**
1. OpenAlex (richest metadata)
2. ACL Anthology
3. DBLP
4. OpenReview
5. ACM Open
6. AAAI OJS

This ensures that when the same paper exists in multiple sources, you get the version with the best metadata.

### Post-Collection Deduplication

If you collected from sources separately (not using `collect-all-sources`), duplicates may exist in the database. Use the deduplicate command to clean them up:

```bash
# Preview duplicates (shows what would be removed)
uv run python -m src.cli.core_collect deduplicate --dry-run

# Remove duplicates (keeps first occurrence)
uv run python -m src.cli.core_collect deduplicate

# Specify collection name
uv run python -m src.cli.core_collect deduplicate --collection my_collection
```

The deduplication identifies:
- **Source ID duplicates**: Same paper collected multiple times from the same source
- **Title+Year cross-source duplicates**: Same paper from different sources

### OpenReview Accepted Papers Only

By default, OpenReview collection only includes **accepted papers**. This filters out rejected and withdrawn submissions, matching official paper counts (e.g., ICLR 2020: ~687 accepted vs ~2,213 total submissions).

To include all submissions (including rejected):

```bash
uv run python -m src.cli.core_collect collect-openreview --venue iclr --include-rejected
```

### Checking for Duplicates

```bash
# Check collection status for duplicate stats
uv run python -m src.cli.core_collect status

# Preview duplicates without removing
uv run python -m src.cli.core_collect deduplicate --dry-run
```

---

## Troubleshooting

### Rate Limiting (429 Errors)

**OpenAlex:**
- Ensure `OPENALEX_EMAIL` is set in `.env`
- The polite pool allows 10 req/sec
- Collection automatically includes delays

**DBLP:**
- Already rate-limited to 1 req/sec
- If issues persist, increase delay in `src/core/dblp.py`

### Resuming Failed Collections

Collections are checkpointed automatically. Simply re-run the same command:

```bash
# This will resume from where it left off
uv run python -m src.cli.core_collect collect --all --since-year 2020
```

To start fresh:
```bash
uv run python -m src.cli.core_collect clear-checkpoint
```

### OpenReview Returns 0 Papers

If OpenReview collection returns 0 papers for recent years, the API version may be incorrect.

**API Version Thresholds:**
| Venue | API v1 | API v2 |
|-------|--------|--------|
| ICLR | ≤2023 | 2024+ |
| NeurIPS | ≤2022 | 2023+ |
| ICML | N/A | 2023+ (only available from 2023) |

The collector automatically selects the correct API version based on venue and year. If you encounter issues, check:
- The year is within the venue's supported range
- Network connectivity to `api.openreview.net` and `api2.openreview.net`

### Connection Errors

```bash
# Test Qdrant connection
uv run python -m src.cli.core_collect init-storage

# Test OpenAlex connection
uv run python -m src.cli.core_collect collect --venue neurips --count-only
```

### Memory Issues

For very large collections, the deduplicator keeps papers in memory. Options:
1. Collect venue-by-venue instead of all at once
2. Restart Python between venues (clears deduplicator memory)

---

## Estimated Collection Times

| Source | Papers (2020+) | Estimated Time |
|--------|---------------|----------------|
| OpenAlex | ~100,000-150,000 | 1-3 hours |
| ACL Anthology (main) | ~20,000 | 5-10 minutes |
| ACL Anthology (workshops) | ~10,000 | 5-10 minutes |
| DBLP | ~5,000 | 15-30 minutes |
| OpenReview | ~15,000 | 30-60 minutes |
| ACM (with abstracts) | ~10,000 | 3-6 hours |
| ACM (no abstracts) | ~10,000 | 15-30 minutes |
| AAAI OJS | ~8,000 | 1-2 hours |
| **Total** | ~170,000-210,000 | **6-12 hours** |

**Note:** Times vary based on network speed and API response times. ACM abstract fetching is slow due to web scraping rate limits.

---

## File Structure

```
src/core/crawler/
├── openalex.py         # OpenAlex collector
├── acl_anthology.py    # ACL Anthology collector
├── dblp.py             # DBLP collector
├── openreview.py       # OpenReview collector (ICLR, NeurIPS, ICML)
├── acm_open.py         # ACM Digital Library collector
├── aaai_ojs.py         # AAAI OJS collector
└── __init__.py         # Exports all collectors

src/core/
├── deduplication.py    # Cross-source deduplication
├── storage.py          # Qdrant storage
├── checkpoint.py       # Resumable checkpoints
└── config.py           # Venue configurations

data/core/checkpoints/
├── collection.json     # OpenAlex checkpoint
├── acl_anthology.json  # ACL checkpoint
├── dblp.json           # DBLP checkpoint
├── openreview.json     # OpenReview checkpoint
├── acm_open.json       # ACM checkpoint
└── aaai_ojs.json       # AAAI checkpoint
```

---

## Workshop Collection

ACL Anthology includes 90+ workshop venues co-located with main NLP conferences. Workshops are identified dynamically by detecting XML files that don't match main venue prefixes.

### Workshop Examples (2024)

| Workshop | Description | Papers |
|----------|-------------|--------|
| BioNLP | Biomedical NLP | ~80 |
| Clinical NLP | Clinical text processing | ~60 |
| ArgMining | Argument Mining | ~20 |
| SemEval | Semantic Evaluation | ~150 |
| BlackboxNLP | Analyzing Neural Networks | ~35 |

### Collecting Workshops

```bash
# Collect only workshops for 2024
uv run python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024

# Collect all main venues + workshops
uv run python -m src.cli.core_collect collect-acl --all --include-workshops

# Use with collect-all-sources
uv run python -m src.cli.core_collect collect-all-sources --include-workshops
```

### Workshop Venue Type

Workshop papers are stored with `venue_type: "workshop"` (Tier 2), allowing filtering:

```python
# Query workshop papers only
from qdrant_client.models import Filter, FieldCondition, MatchValue

workshop_filter = Filter(must=[
    FieldCondition(key="venue_type", match=MatchValue(value="workshop"))
])
```

---

## Data Quality Dashboard

Before running enrichment, check data quality to understand coverage gaps.

### Check Data Quality

```bash
# Show data quality report
uv run python -m src.cli.core_collect data-quality

# Output as JSON (for scripting)
uv run python -m src.cli.core_collect data-quality --json

# Show breakdown by venue
uv run python -m src.cli.core_collect data-quality --by-venue
```

### Sample Output

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

=== Enrichment Potential ===
Citation enrichment: 10,926 papers (have DOI, missing refs)
Abstract enrichment: 1,330 papers (have DOI, missing abstract)
```

---

## Citation Enrichment

Papers collected from ACL Anthology and OpenReview don't include citation data (`referenced_works`).
Use the enrichment pipeline to fetch citations from OpenAlex.

### Why Enrichment?

| Source | Has `referenced_works` |
|--------|----------------------|
| OpenAlex | Yes |
| ACL Anthology | No |
| OpenReview | No |
| DBLP | No |

Only ~19% of papers have citation data after initial collection. Enrichment can increase this to ~55%.

### Check Enrichment Status

```bash
# Count papers needing enrichment (dry run)
uv run python -m src.cli.core_collect enrich-citations --dry-run
```

### Run Enrichment

```bash
# Enrich all papers with DOI (sequential)
uv run python -m src.cli.core_collect enrich-citations

# Enrich with parallel requests (faster)
uv run python -m src.cli.core_collect enrich-citations --parallel 10

# Enrich with limit (for testing)
uv run python -m src.cli.core_collect enrich-citations --limit 1000

# Resume from checkpoint (automatic)
uv run python -m src.cli.core_collect enrich-citations
```

### Checkpoint & Resume

Enrichment progress is saved to `data/core/checkpoints/citation_enrichment.json`.
If interrupted, simply run the command again to resume.

```bash
# Clear checkpoint to start fresh
uv run python -m src.cli.core_collect clear-enrichment-checkpoint
```

### Rate Limits & Parallelism

| Configuration | Request Limit | Recommended `--parallel` |
|---------------|---------------|-------------------------|
| With `OPENALEX_API_KEY` | 100,000/day | 10 |
| With `OPENALEX_EMAIL` only | ~10,000/day | 5 |
| No auth | ~1,000/day | 1 (sequential) |

### Expected Results

| Papers | Can Enrich | Notes |
|--------|------------|-------|
| ACL papers with DOI | ~61% (7,754) | Main enrichment target |
| Other sources with DOI | ~27% (3,172) | OpenReview, DBLP, etc. |
| **Total** | ~55% coverage | Up from 19% |

---

## Abstract Enrichment

DBLP papers (~5,000) have no abstracts, reducing search quality.
Use abstract enrichment to fetch missing abstracts from OpenAlex.

### Why Abstract Enrichment?

| Source | Has Abstracts |
|--------|---------------|
| OpenAlex | Yes |
| ACL Anthology | Yes |
| OpenReview | Yes |
| ACM Open | Yes |
| AAAI OJS | Yes |
| **DBLP** | **No** |

### Check Abstract Status

```bash
# Count papers needing abstract enrichment
uv run python -m src.cli.core_collect enrich-abstracts --dry-run
```

### Run Abstract Enrichment

```bash
# Enrich all papers missing abstracts
uv run python -m src.cli.core_collect enrich-abstracts

# Enrich with parallel requests
uv run python -m src.cli.core_collect enrich-abstracts --parallel 10

# Enrich with limit (for testing)
uv run python -m src.cli.core_collect enrich-abstracts --limit 100
```

### Checkpoint & Resume

```bash
# Clear checkpoint for fresh start
uv run python -m src.cli.core_collect clear-enrichment-checkpoint --type abstracts
```

---

## Semantic Scholar Enrichment

When OpenAlex doesn't have citation data (common for 2024 papers), use Semantic Scholar as a fallback. S2 often has better coverage for ML/AI papers.

### Prerequisites

Get an S2 API key for higher rate limits: https://www.semanticscholar.org/product/api#api-key

```env
S2_API_KEY=your-api-key
```

### Enrich by DOI (Fallback for OpenAlex)

```bash
# Enrich papers that have DOIs but OpenAlex failed
uv run python -m src.cli.core_collect enrich-s2

# With parallel requests (S2 has strict limits, keep low)
uv run python -m src.cli.core_collect enrich-s2 --parallel 3

# Limit to specific number of papers
uv run python -m src.cli.core_collect enrich-s2 --limit 500
```

### Enrich by Title (For Papers Without DOIs)

This is essential for OpenReview papers (NeurIPS, ICML, ICLR) which have no DOIs:

```bash
# Search S2 by title for papers without DOIs
uv run python -m src.cli.core_collect enrich-s2 --by-title

# Target specific venues
uv run python -m src.cli.core_collect enrich-s2 --by-title -v "NeurIPS 2024 poster"
uv run python -m src.cli.core_collect enrich-s2 --by-title -v "ICML 2024 Poster" -v "ICLR 2024 poster"

# Require minimum references for match quality
uv run python -m src.cli.core_collect enrich-s2 --by-title --min-refs 5
```

### Checkpoint & Resume

```bash
# Clear S2 checkpoint
uv run python -m src.cli.core_collect clear-s2-checkpoint
```

### Expected Results

S2 typically achieves ~25-30% success rate on papers where OpenAlex failed.

---

## PDF Reference Extraction (Last Resort)

When API-based methods fail, extract references directly from PDFs using GROBID.

### Prerequisites

Start GROBID server (requires Docker):

```bash
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
```

### Extract References

```bash
# Count papers with PDF URLs
uv run python -m src.cli.core_collect extract-pdf-refs --dry-run

# Extract from all PDFs
uv run python -m src.cli.core_collect extract-pdf-refs --parallel 2

# Target specific venues
uv run python -m src.cli.core_collect extract-pdf-refs -v "NeurIPS 2024 poster"

# Limit for testing
uv run python -m src.cli.core_collect extract-pdf-refs --limit 100
```

### Checkpoint & Resume

```bash
# Clear PDF extraction checkpoint
uv run python -m src.cli.core_collect clear-pdf-checkpoint
```

### Limitations

- Slower than API methods (requires downloading and processing PDFs)
- Quality depends on PDF structure
- May not extract DOIs for all references

---

## Recommended Enrichment Pipeline

Run enrichments in this order for best results:

```bash
# 1. OpenAlex (fast, best for older papers)
uv run python -m src.cli.core_collect enrich-citations --parallel 10

# 2. Semantic Scholar DOI (fallback for papers OpenAlex missed)
uv run python -m src.cli.core_collect enrich-s2 --parallel 3

# 3. Semantic Scholar Title (for papers without DOIs)
uv run python -m src.cli.core_collect enrich-s2 --by-title --parallel 3

# 4. PDF Extraction (last resort, slowest)
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0 &
uv run python -m src.cli.core_collect extract-pdf-refs --parallel 2
```

---

## Reference Resolution (Citation Graph)

After collecting and enriching papers, you can resolve `referenced_works` identifiers to internal Qdrant point IDs to build a citation graph.

### Why Reference Resolution?

The `referenced_works` field contains raw identifiers in mixed formats:
- `DOI:10.18653/v1/2020.acl-main.1` - DOIs
- `arXiv:2303.08774` - arXiv IDs (some malformed as `arXiv:arXiv:...`)
- `TITLE:attention is all you need` - Title-based fallbacks

Reference resolution creates a `resolved_references` field containing internal Qdrant point IDs, enabling:
- Citation graph traversal
- Citation-based paper recommendations
- Impact analysis

### Pipeline Steps

```
Step 1: Normalize          Step 2: arXiv→DOI         Step 3: Resolve to IDs
─────────────────         ─────────────────         ─────────────────────
arXiv:arXiv:2303  →  arXiv:2303.08774  →  DOI:10.xxx  →  point_id (UUID)
DOI:10.XXX        →  DOI:10.xxx (lower)              →  point_id (UUID)
TITLE:attention...→  TITLE:attention...             →  point_id (UUID)
```

### Running Reference Resolution

```bash
# Check statistics first
uv run python -m src.cli.core_collect ref-stats

# Run full pipeline (dry run to preview)
uv run python -m src.cli.core_collect resolve-refs --dry-run

# Run full pipeline
uv run python -m src.cli.core_collect resolve-refs

# Run specific steps
uv run python -m src.cli.core_collect resolve-refs --step normalize
uv run python -m src.cli.core_collect resolve-refs --step arxiv
uv run python -m src.cli.core_collect resolve-refs --step internal

# With fuzzy title matching (slower but better coverage)
uv run python -m src.cli.core_collect resolve-refs --step internal --fuzzy-matching

# Search external APIs for unresolved titles (adds papers to corpus)
uv run python -m src.cli.core_collect resolve-refs --step internal --external-search

# Limit papers processed
uv run python -m src.cli.core_collect resolve-refs --limit 1000
```

### Step Details

#### Step 1: Normalize

Fixes malformed identifiers:
- `arXiv:arXiv:2303.08774` → `arXiv:2303.08774`
- DOI case normalization
- Prefix standardization

```bash
uv run python -m src.cli.core_collect resolve-refs --step normalize --limit 100
uv run python -m src.cli.core_collect ref-stats
# Verify no "arXiv:arXiv:" duplicates remain
```

#### Step 2: arXiv→DOI

Converts arXiv references to DOIs via OpenAlex lookup:

```bash
uv run python -m src.cli.core_collect resolve-refs --step arxiv --limit 100
uv run python -m src.cli.core_collect ref-stats
# Check arXiv count decreased, DOI count increased
```

#### Step 3: Resolve to Internal IDs

Maps identifiers to Qdrant point IDs:

```bash
uv run python -m src.cli.core_collect resolve-refs --step internal --limit 100
uv run python -m src.cli.core_collect ref-stats
# Should show papers_with_resolved > 0
```

### Checkpoint Management

Progress is automatically checkpointed for resumable operation:

```bash
# Clear all checkpoints
uv run python -m src.cli.core_collect clear-resolve-checkpoint

# Clear specific step
uv run python -m src.cli.core_collect clear-resolve-checkpoint --step normalize
uv run python -m src.cli.core_collect clear-resolve-checkpoint --step arxiv
uv run python -m src.cli.core_collect clear-resolve-checkpoint --step internal
```

### Verifying Graph Connectivity

```python
from src.core.storage import QdrantStorage
storage = QdrantStorage()

# Get paper with resolved refs
results, _ = storage.client.scroll('lexicon_arxiv', limit=1,
    scroll_filter={"must_not": [
        {"is_empty": {"key": "resolved_references"}}
    ]},
    with_payload=["title", "resolved_references"])
paper = results[0]

# Verify refs point to real papers
for ref_id in paper.payload["resolved_references"][:3]:
    ref_paper = storage.client.retrieve('lexicon_arxiv', ids=[ref_id])
    print(f"  -> {ref_paper[0].payload['title']}")
```

### Expected Coverage

| Step | Input | Output |
|------|-------|--------|
| Normalize | `arXiv:arXiv:2303.08774` | `arXiv:2303.08774` |
| arXiv→DOI | `arXiv:2303.08774` | `DOI:10.xxx` (via OpenAlex) |
| Resolve DOI | `DOI:10.xxx` | `point_id` (if in corpus) |
| Resolve arXiv | `arXiv:2303.08774` | `point_id` (if in corpus) |
| Resolve TITLE | `TITLE:attention is...` | `point_id` (if title matches) |

**Coverage estimate:**
- Internal matches: ~30-50% of references
- With external search: ~70-90% (adds papers not in corpus)

### Schema Changes

After resolution, papers have:

```python
{
    # Existing - raw identifiers
    "referenced_works": ["DOI:10.18653/v1/...", "arXiv:2303.08774", "TITLE:..."],

    # New - internal paper IDs
    "resolved_references": ["550e8400-e29b-41d4-a716-446655440000", "6fa459ea-..."],
}
```

---

## Keyword Extraction

After collecting and enriching papers, extract keywords for improved BM25 search.

### Why Keyword Extraction?

Keywords enable exact paper retrieval:
- "give me the HyDE paper" → matches `keywords: ["HyDE"]`
- "BERT paper" → matches `keywords: ["BERT"]`

Without keywords, these queries rely solely on title/abstract text matching.

### LLM-First Extraction

1. **LLM Extraction** (primary): Structured keyword extraction via Gemini or Ollama
   - Works with or without abstract (title-only supported)
   - Returns categorized keywords: task, method, model, domain, dataset, contribution_type, modality

2. **Fallback**: Regex + KeyBERT (only when LLM is unavailable or fails)
   - `"BERT: Pre-training..."` → `["BERT"]`
   - `"...retrieval augmented generation..."` → `["retrieval augmented", "generation"]`

### Running Keyword Extraction

```bash
# Check statistics first
uv run python -m src.cli.core_collect keyword-stats

# LLM-first pipeline (recommended)
uv run python -m src.cli.core_collect extract-keywords --llm --judge

# Preview extraction (dry run)
uv run python -m src.cli.core_collect extract-keywords --llm --judge --dry-run --limit 10

# Fallback only: regex + KeyBERT (no LLM)
uv run python -m src.cli.core_collect extract-keywords

# Regex only (faster, no ML model)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Limit for testing
uv run python -m src.cli.core_collect extract-keywords --limit 1000
```

### Checkpoint Management

```bash
# Clear checkpoint to start fresh
uv run python -m src.cli.core_collect clear-keyword-checkpoint
```

### Expected Results

| Metric | Expected Value |
|--------|----------------|
| Papers with keywords | ~90% of corpus |
| Avg keywords per paper | 3-5 |
| Acronym precision | >95% |

### Dependencies

KeyBERT requires additional dependencies:

```bash
uv pip install keybert sentence-transformers
```

### Schema Changes

After extraction, papers have:

```python
{
    "keywords": ["BERT", "language model", "pre-training"],
    "keywords_source": "gemini|judge"  # e.g., "gemini", "ollama|judge", "regex|keybert"
}
```

---

## Recommended Full Pipeline

For a complete corpus with all enrichments:

```bash
# 1. Collect from all sources
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# 2. Deduplicate
uv run python -m src.cli.core_collect deduplicate

# 3. Enrich citations and abstracts
uv run python -m src.cli.core_collect enrich-citations --parallel 10
uv run python -m src.cli.core_collect enrich-abstracts --parallel 10

# 4. Resolve references (build citation graph)
uv run python -m src.cli.core_collect resolve-refs

# 5. Build citation graph metrics
uv run python -m src.cli.core_collect build-cited-by

# 6. Extract keywords (for BM25 search)
uv run python -m src.cli.core_collect extract-keywords --llm --judge
```

---

## See Also

- [Data Collection Design](../pipelines/data_collection.md)
- [Keyword Extraction Design](../pipelines/keyword_extraction.md)
- [Architecture Overview](../architecture/overview.md)
- [Data Model](../architecture/data_model.md)
- [CLI Reference](../reference/cli.md)
- [Venue Reference](../reference/venues.md)
