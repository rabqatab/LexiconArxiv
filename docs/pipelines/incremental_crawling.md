# Incremental Crawling Strategy

This document describes the incremental update strategy for keeping the LexiconArxiv corpus up-to-date after initial collection.

## 1. Overview

### 1.1 The Challenge

Each data source has different APIs, update patterns, and limitations:

| Source | API Type | Date Filtering | Update Pattern | Challenges |
|--------|----------|----------------|----------------|------------|
| **OpenAlex** | REST API | `from_updated_date` (Premium) | Daily updates | Requires Premium plan since early 2026 |
| **ACL Anthology** | GitHub XML files | None (file-based) | Batch releases | No date filter, pattern changes |
| **OpenReview** | REST API | `mdate` field | Conference cycles | Invitation patterns change yearly |
| **DBLP** | XML dump | None | Monthly updates | Bulk download only |
| **ACM Open** | Web scraping | None | Unknown | Rate limited |
| **AAAI OJS** | Web scraping | None | Annual | Only 2020-2023 |

### 1.2 Current Implementation

The `collect-incremental` command provides basic incremental updates:

```bash
# Papers updated in last 24 hours
uv run python -m src.cli.core_collect collect-incremental

# Papers updated in last 7 days
uv run python -m src.cli.core_collect collect-incremental --days 7

# Only specific source
uv run python -m src.cli.core_collect collect-incremental --source openalex
```

**How it works:**
- **OpenAlex**: Uses `from_updated_date` API filter (truly incremental)
- **Other sources**: Re-runs collection for current year only (relies on checkpoint deduplication)

---

## 2. Source-Specific Details

### 2.1 OpenAlex (Best for Incremental)

OpenAlex is the most reliable source for incremental updates due to native date filtering support.

```python
# API supports date-based filtering
GET /works?filter=from_updated_date:2026-01-01
```

**Pros:**
- Native `from_updated_date` and `from_created_date` filters
- Updates propagate within 24-48 hours
- Consistent API across all venues

**Cons:**
- `from_updated_date` requires Premium/Institutional/Partner plan since early 2026 (falls back to `publication_year` range filtering)
- Slow to index new NLP papers (ACL, EMNLP have 87% coverage gap)
- May miss papers not yet in their database

**Recommended for:** Journals (JMLR, TOIS, ESWA), well-indexed ML venues (KDD, SIGIR)

### 2.2 ACL Anthology (File-Based)

ACL Anthology stores papers in XML files on GitHub. No date-based API exists.

```
https://github.com/acl-org/acl-anthology/tree/master/data/xml
├── 2024.acl.xml
├── 2024.emnlp.xml
├── 2025.acl.xml      # New files appear when proceedings are published
└── 2025.naacl.xml
```

**Current Incremental Strategy:**
1. Use Git Trees API to list all XML files (fixes 1000-file pagination limit)
2. Compare against processed files in checkpoint
3. Download and parse only new/modified files

**Known Issues:**
- File naming patterns change between years:
  - 2023: `NeurIPS.cc/2023/Track/Datasets_and_Benchmarks`
  - 2024: `NeurIPS.cc/2024/Datasets_and_Benchmarks_Track`
- GitHub API pagination limit (1000 files) - fixed with Trees API
- Publication lag: Proceedings appear weeks/months after conference

**Recommended for:** All NLP venues (ACL, EMNLP, NAACL, EACL, COLING, Findings, workshops)

### 2.3 OpenReview (Conference-Based)

OpenReview hosts ML conference submissions with review data.

```python
# API v2 (2023+)
GET /notes?invitation=NeurIPS.cc/2024/Conference/-/Submission

# Supports sorting by modification date
GET /notes?invitation=...&sort=mdate:desc
```

**Current Incremental Strategy:**
1. Query for papers modified since last update
2. Filter to accepted papers using `content.venue` field
3. Handle API v1 vs v2 differences

**Known Issues:**
- Invitation patterns change yearly:
  ```
  # 2023 D&B track
  NeurIPS.cc/2023/Track/Datasets_and_Benchmarks/-/Submission

  # 2024 D&B track
  NeurIPS.cc/2024/Datasets_and_Benchmarks_Track/-/Submission
  ```
- Need to maintain alternative patterns for each venue/year
- API v2 migration happened at different times for different venues

**Recommended for:** ICLR, NeurIPS, ICML, AAAI (2024+)

### 2.4 DBLP (Bulk Updates)

DBLP provides XML dumps rather than an incremental API.

**Current Strategy:**
- Re-run collection for current year
- Checkpoint prevents duplicate processing
- No true incremental capability

**Recommended for:** RecSys, ECIR, WSDM, CIKM, ICAIL, JURIX (venues with poor OpenAlex coverage)

---

## 3. Full Incremental Pipeline

The incremental pipeline runs all post-crawling steps (enrichment, keywords, labeling, resolution, graph, **embedding**), plus optional weekly maintenance (similarity graph, graph analysis) and quarterly topic re-clustering.

### 3.1 Pipeline Script

Use the provided script for complete incremental updates:

```bash
# Daily update (default: 1 day) — collect + enrich + keywords + labeling + graph + embed
./scripts/run_incremental_pipeline.sh

# Weekly update + maintenance (recompute similarity graph + graph analysis)
./scripts/run_incremental_pipeline.sh --days 7 --weekly

# Quarterly update + maintenance + topic re-clustering
./scripts/run_incremental_pipeline.sh --days 90 --weekly --cluster

# Skip graph rebuild and/or embedding (faster)
./scripts/run_incremental_pipeline.sh --days 7 --skip-graph --skip-embed

# Dry run (preview steps only, no execution)
./scripts/run_incremental_pipeline.sh --days 90 --weekly --dry-run
```

**Pipeline Steps:**
1. `collect-incremental --days N` — Collect new papers from all sources
2. `enrich-6-abstracts-by-doi-via-openalex` — Fill missing abstracts via OpenAlex
3. `enrich-4-refs-by-doi-via-s2 --recent-days N` — Enrich citations via Semantic Scholar (recent papers only; with `--weekly` the full backlog also runs in the background)
4. `enrich-2-refs-by-doi-via-crossref` — Enrich citations via CrossRef (papers S2 missed)
5. `extract-keywords` — Extract keywords for BM25 search *(runs in parallel with step 6)*
6. `label-abstracts` — Label abstract sentences with rhetorical roles *(parallel; skip with `--skip-labeling`)*
7. `resolve-refs --create-stubs` — Resolve references and create stub papers
8. `enrich-8-metadata-by-stub-via-openalex` — Enrich stub paper metadata
9. `build-cited-by --incremental` — Update the cited_by citation graph *(skip with `--skip-graph`)*
10. `embed-papers` — Embed new papers: dense + section-level + BM25 vectors *(skip with `--skip-embed`)*

**Weekly maintenance** (`--weekly`):

11. `compute-similarity` — Recompute the semantic similarity graph (typed section-level edges)
12. `analyze-citation-graph --all --store` — Recompute graph analysis (PageRank, HITS, communities)

**Quarterly** (`--cluster`):

13. `compute-topics` — Recompute UMAP + HDBSCAN topic clusters

All steps are **incremental** — they only process new/unenriched papers. Flags: `--days N`, `--parallel N`, `--weekly`, `--cluster`, `--skip-graph`, `--skip-labeling`, `--skip-embed`, `--dry-run`.

---

## 4. Crontab Configuration

### 4.1 Daily Updates

```bash
# /etc/cron.d/lexiconarxiv-daily
# Mon-Sat at 2 AM - collect + enrich + embed (Sunday reserved for the weekly run)
0 2 * * 1-6 cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh >> logs/cron_daily.log 2>&1
```

### 4.2 Weekly Updates

```bash
# /etc/cron.d/lexiconarxiv-weekly
# Weekly on Sunday at 2 AM - includes similarity graph + graph analysis maintenance
0 2 * * 0 cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 7 --weekly >> logs/cron_weekly.log 2>&1
```

### 4.3 Quarterly Updates (Recommended for Low-Maintenance)

```bash
# /etc/cron.d/lexiconarxiv-quarterly
# Quarterly: 1st of Jan, Apr, Jul, Oct at 2 AM - includes topic re-clustering
0 2 1 1,4,7,10 * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 --weekly --cluster >> logs/cron_quarterly.log 2>&1
```

### 4.4 Setting Up Crontab

```bash
# Edit user crontab
crontab -e

# Or create system crontab file
sudo nano /etc/cron.d/lexiconarxiv

# View current crontab
crontab -l
```

**Example complete crontab entry:**

```cron
# LexiconArxiv Quarterly Update
# Runs on 1st of January, April, July, October at 2:00 AM
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
MAILTO=your-email@example.com

0 2 1 1,4,7,10 * cd /home/user/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 --weekly --cluster >> logs/cron.log 2>&1
```

### 4.5 Post-Conference Collection

After major conferences publish proceedings, run targeted collection manually:

```bash
# After ACL 2025 proceedings are published
uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2025

# After NeurIPS 2025
uv run python -m src.cli.core_collect collect-openreview --venue neurips --since-year 2025

# Then run enrichment pipeline
./scripts/run_incremental_pipeline.sh --days 1 --skip-graph
```

---

## 5. Monitoring and Alerts

### 5.1 Expected Paper Counts by Year

Track these metrics to detect collection issues:

| Venue | Expected/Year | Alert if Below |
|-------|---------------|----------------|
| NeurIPS | ~5,000 | 4,000 |
| ICML | ~2,500 | 2,000 |
| ICLR | ~2,500 | 2,000 |
| ACL | ~1,000 | 800 |
| EMNLP | ~1,500 | 1,200 |
| AAAI | ~3,000 | 2,500 |

### 5.2 Check Collection Status

```bash
# Overall status
uv run python -m src.cli.core_collect status

# Papers by year and venue
uv run python -m src.cli.core_collect stats --by-year --by-venue
```

---

## 6. Known Issues and Workarounds

### 6.1 ACL Anthology 2025 Files Not Found

**Issue:** GitHub Contents API returns max 1000 files, missing newer 2025 files.

**Fix:** Use Git Trees API instead (implemented in `acl_anthology.py`):
```python
GITHUB_TREES_API = "https://api.github.com/repos/acl-org/acl-anthology/git/trees/master?recursive=1"
```

### 6.2 NeurIPS Datasets & Benchmarks Track Missing

**Issue:** D&B track has separate invitation pattern not in main config.

**Fix:** Added `neurips_db` venue with alternative patterns:
```python
"neurips_db": {
    "invitation_pattern_v2": "NeurIPS.cc/{year}/Datasets_and_Benchmarks_Track/-/Submission",
    "invitation_pattern_v2_alt": "NeurIPS.cc/{year}/Track/Datasets_and_Benchmarks/-/Submission",
}
```

### 6.3 AACL/IJCNLP Missing

**Issue:** AACL papers stored under `ijcnlp.xml` prefix.

**Fix:** Added AACL venue with both prefixes:
```python
"aacl": {
    "prefixes": ["aacl", "ijcnlp"],
}
```

### 6.4 OpenAlex from_updated_date (Premium Required)

As of early 2026, OpenAlex's `from_updated_date` filter requires a Premium, Institutional, or Partner plan. The incremental collector falls back to `publication_year` range filtering with checkpoint-based deduplication. This means incremental runs scan all papers for the target year(s) rather than only recently updated ones.

### 6.5 OpenAlex Slow to Index NLP Papers

**Issue:** OpenAlex has 87% coverage gap for NLP venues (ACL, EMNLP, etc.)

**Workaround:** Use ACL Anthology as primary source for NLP venues, not OpenAlex.

### 6.6 Incremental --days Only Affected OpenAlex (Fixed in v0.7.2)

**Issue:** The `--days` parameter only worked for OpenAlex. Other sources used `current_year` only, missing papers from the previous year when running in January-March.

**Fix:** Now calculates `since_year` from the date range, correctly spanning year boundaries:
```bash
# Running in March 2026 with --days 90
# Before: Only collected 2026 papers (missed late 2025)
# After:  Collects 2025-2026 papers correctly
uv run python -m src.cli.core_collect collect-incremental --days 90
```

### 6.7 build_cited_by Connection Reset (Fixed in v0.7.2)

**Issue:** `build_cited_by` crashed with "Connection reset by peer" when updating 100k+ papers.

**Fix:** Added retry logic, smaller batches (50 ops), and delays between batches.

---

### 6.8 --recent-days for S2 Enrichment and force=True for Collection

The Semantic Scholar enrichment step supports a `--recent-days N` flag to limit enrichment to papers added within the last N days, reducing API calls during incremental runs:

```bash
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --recent-days 7
```

For collection commands, passing `force=True` (or `--force` on the CLI) skips checkpoint-based deduplication and re-collects all papers for the target venue/year range. This is useful after fixing a collector bug or when checkpoint data is stale:

```bash
uv run python -m src.cli.core_collect collect-openalex --venue neurips --since-year 2025 --force
```

---

## 7. First Incremental Loop Results (March 2026)

The first real incremental crawling-preprocessing loop ran March 28-30, 2026. This section documents actual results, timings, and lessons learned.

### 7.1 Collection Results

| Source | New Papers | Notes |
|--------|-----------|-------|
| OpenAlex | 6,089 | `publication_year` fallback (Premium required for `from_updated_date`) |
| ACL Anthology | 999 | Required `force=True` to bypass `is_complete` checkpoint flag |
| DBLP | 187 | Required `force=True` to bypass `is_complete` checkpoint flag |
| OpenReview | 0 | 2026 papers not yet public |
| AAAI OJS | 0 | No new papers available |
| **Total** | **7,275** | **Corpus grew from 145K to 152,769 core papers** |

### 7.2 Enrichment Results

| Stage | Result | Notes |
|-------|--------|-------|
| Abstracts (OpenAlex) | 17,561 enriched | Covers both new and previously missed papers |
| S2 citations | 369 enriched | 7,229 papers scanned in 12 min after stub-exclusion fix |
| CrossRef citations | 20,796 enriched | |
| Keywords | Done | regex + KeyBERT |
| Labeling | Done | Gemini, ~4,400 calls, ~$3 cost |
| Reference resolution | Done | |
| Cited_by | Done | Incremental rebuild |
| Embedding | 167 new papers | Section-level + BM25 |

### 7.3 Issues Encountered and Fixes Applied

1. **OpenAlex `from_updated_date` requires Premium** -- The free tier no longer supports date-based incremental filtering. The collector now falls back to `publication_year` range filtering with checkpoint deduplication.
2. **OpenAlex 429 rate limits** -- Transient vs quota-exhaustion 429s are now distinguished; same-key retry is used for transient errors.
3. **Non-OpenAlex sources skipped by `is_complete` flag** -- ACL, DBLP, OpenReview, ACM, and AAAI all returned 0 papers because checkpoints were marked complete from the initial collection. Fix: pass `force=True` (or `--force` on CLI) to bypass the flag.
4. **OpenReview missing `httpx` import** -- Runtime error on OpenReview collection; fixed with the missing import.
5. **S2 enricher scrolled 666K papers (including stubs)** -- Added `must_not: [is_stub=true]` filter to `get_papers_missing_references()`, reducing scroll from 666K to 7K papers.
6. **S2 `--recent-days` flag** -- Added for prioritized incremental enrichment of recently collected papers.
7. **S2 multi-key rotation** -- Two keys with concurrency=2 for parallel enrichment.
8. **QdrantStorage facade missing `fetched_since` passthrough** -- Fixed the facade to forward `fetched_since` to the underlying storage methods.

### 7.4 Recommended Configuration for Future Runs

```bash
# 1. Collection: use --force for non-OpenAlex sources
./scripts/run_incremental_pipeline.sh --days 7

# Or manually with force for sources that checkpoint as complete:
uv run python -m src.cli.core_collect collect-incremental --days 7 --force

# 2. S2 enrichment: use --recent-days to limit scope
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --recent-days 7

# 3. Full pipeline takes ~30-60 minutes depending on new paper volume
```

**Key takeaways:**
- Always use `--force` for non-OpenAlex sources in incremental runs, since checkpoints mark them as complete after initial collection.
- The S2 enricher should always be run with `--recent-days` to avoid scanning the entire corpus.
- OpenAlex `from_updated_date` requires a Premium plan; without it, expect full-year scans with deduplication.
- Gemini labeling cost is modest (~$3 for ~4,400 calls) and can be run on every incremental loop.

---

## 8. Future Improvements

### 8.1 Proposed: Unified Incremental System

```
┌─────────────────────────────────────────────────────────────────┐
│                 Unified Incremental Update System                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Track last_updated timestamp per source in checkpoint        │
│                                                                  │
│  2. Source-specific incremental logic:                           │
│     ├── OpenAlex: from_updated_date filter                       │
│     ├── ACL Anthology: Git tree hash comparison                  │
│     ├── OpenReview: mdate > last_update filter                   │
│     └── Others: Current year only (fallback)                     │
│                                                                  │
│  3. Automatic pattern discovery for new venues/years             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Proposed: RSS/Webhook Integration

- ACL Anthology: Monitor GitHub releases
- OpenReview: Webhook for new decisions
- DBLP: Monthly XML diff

---

## 9. Troubleshooting

### Incremental Returns 0 Papers

1. Check if checkpoint marked venue as complete:
   ```bash
   cat data/core/checkpoints/*.json | grep -A5 "venue_name"
   ```

2. Clear checkpoint for specific venue:
   ```bash
   uv run python -m src.cli.core_collect clear-checkpoint --venue acl_acl
   ```

3. Re-run collection:
   ```bash
   uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2025
   ```

### New Venue/Year Not Collected

1. Check if venue exists in config:
   ```bash
   uv run python -m src.cli.core_collect list-openreview-venues
   ```

2. If new track (e.g., NeurIPS D&B 2025), check invitation pattern:
   ```bash
   curl "https://api2.openreview.net/groups?prefix=NeurIPS.cc/2025" | jq '.groups[].id'
   ```

3. Add new venue/pattern to crawler config if needed.
