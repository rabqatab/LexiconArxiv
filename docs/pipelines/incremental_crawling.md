# Incremental Crawling Strategy

This document describes the incremental update strategy for keeping the LexiconArxiv corpus up-to-date after initial collection.

## 1. Overview

### 1.1 The Challenge

Each data source has different APIs, update patterns, and limitations:

| Source | API Type | Date Filtering | Update Pattern | Challenges |
|--------|----------|----------------|----------------|------------|
| **OpenAlex** | REST API | `from_updated_date` | Daily updates | Best for incremental |
| **ACL Anthology** | GitHub XML files | None (file-based) | Batch releases | No date filter, pattern changes |
| **OpenReview** | REST API | `mdate` field | Conference cycles | Invitation patterns change yearly |
| **DBLP** | XML dump | None | Monthly updates | Bulk download only |
| **ACM Open** | Web scraping | None | Unknown | Rate limited |
| **AAAI OJS** | Web scraping | None | Annual | Only 2020-2023 |

### 1.2 Current Implementation

The `collect-incremental` command provides basic incremental updates:

```bash
# Papers updated in last 24 hours
python -m src.cli.core_collect collect-incremental

# Papers updated in last 7 days
python -m src.cli.core_collect collect-incremental --days 7

# Only specific source
python -m src.cli.core_collect collect-incremental --source openalex
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

The incremental pipeline includes all post-crawling steps (enrichment, keywords, resolution, graph).

### 3.1 Pipeline Script

Use the provided script for complete incremental updates:

```bash
# Daily update (default: 1 day)
./scripts/run_incremental_pipeline.sh

# Weekly update
./scripts/run_incremental_pipeline.sh --days 7

# Monthly update
./scripts/run_incremental_pipeline.sh --days 30

# Quarterly update (3 months)
./scripts/run_incremental_pipeline.sh --days 90

# Skip graph rebuild (faster)
./scripts/run_incremental_pipeline.sh --days 90 --skip-graph

# Dry run (preview only)
./scripts/run_incremental_pipeline.sh --days 90 --dry-run
```

**Pipeline Steps:**
1. `collect-incremental` - Collect new papers from all sources
2. `enrich-abstracts` - Fill missing abstracts via OpenAlex
3. `enrich-s2` - Enrich citations via Semantic Scholar
4. `enrich-crossref` - Enrich citations via CrossRef (fallback)
5. `extract-keywords` - Extract keywords for BM25 search
6. `resolve-refs` - Resolve references and create stubs
7. `enrich-stubs` - Enrich stub paper metadata
8. `build-citation-graph` - Rebuild the citation graph

All steps are **incremental** - they only process new/unenriched papers.

---

## 4. Crontab Configuration

### 4.1 Daily Updates

```bash
# /etc/cron.d/lexiconarxiv-daily
# Daily at 2 AM - full pipeline
0 2 * * * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh >> logs/cron_daily.log 2>&1
```

### 4.2 Weekly Updates

```bash
# /etc/cron.d/lexiconarxiv-weekly
# Weekly on Sunday at 3 AM
0 3 * * 0 cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 7 >> logs/cron_weekly.log 2>&1
```

### 4.3 Quarterly Updates (Recommended for Low-Maintenance)

```bash
# /etc/cron.d/lexiconarxiv-quarterly
# Quarterly: 1st of Jan, Apr, Jul, Oct at 2 AM
0 2 1 1,4,7,10 * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 >> logs/cron_quarterly.log 2>&1
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

0 2 1 1,4,7,10 * cd /home/user/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 >> logs/cron.log 2>&1
```

### 4.5 Post-Conference Collection

After major conferences publish proceedings, run targeted collection manually:

```bash
# After ACL 2025 proceedings are published
python -m src.cli.core_collect collect-acl --venue acl --since-year 2025

# After NeurIPS 2025
python -m src.cli.core_collect collect-openreview --venue neurips --since-year 2025

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
python -m src.cli.core_collect status

# Papers by year and venue
python -m src.cli.core_collect stats --by-year --by-venue
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

### 6.4 OpenAlex Slow to Index NLP Papers

**Issue:** OpenAlex has 87% coverage gap for NLP venues (ACL, EMNLP, etc.)

**Workaround:** Use ACL Anthology as primary source for NLP venues, not OpenAlex.

---

## 7. Future Improvements

### 7.1 Proposed: Unified Incremental System

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

### 7.2 Proposed: RSS/Webhook Integration

- ACL Anthology: Monitor GitHub releases
- OpenReview: Webhook for new decisions
- DBLP: Monthly XML diff

---

## 8. Troubleshooting

### Incremental Returns 0 Papers

1. Check if checkpoint marked venue as complete:
   ```bash
   cat data/core/checkpoints/*.json | grep -A5 "venue_name"
   ```

2. Clear checkpoint for specific venue:
   ```bash
   python -m src.cli.core_collect clear-checkpoint --venue acl_acl
   ```

3. Re-run collection:
   ```bash
   python -m src.cli.core_collect collect-acl --venue acl --since-year 2025
   ```

### New Venue/Year Not Collected

1. Check if venue exists in config:
   ```bash
   python -m src.cli.core_collect list-openreview-venues
   ```

2. If new track (e.g., NeurIPS D&B 2025), check invitation pattern:
   ```bash
   curl "https://api2.openreview.net/groups?prefix=NeurIPS.cc/2025" | jq '.groups[].id'
   ```

3. Add new venue/pattern to crawler config if needed.
