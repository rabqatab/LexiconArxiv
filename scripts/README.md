# LexiconArxiv Scripts

Shell scripts for running data pipelines.

## Quick Start

```bash
# Run full pipeline (collection → dedup → enrichment → resolution)
./scripts/run_full_pipeline.sh --since-year 2020

# Or run individual stages
./scripts/crawler/run_full_collection.sh --since-year 2020
./scripts/maintenance/run_deduplication.sh --apply
./scripts/enrichment/run_enrichment.sh
./scripts/resolution/run_resolution.sh
```

---

## Directory Structure

```
scripts/
├── run_full_pipeline.sh      # Full 4-stage pipeline
├── crawler/                  # Data collection scripts
│   ├── run_full_collection.sh
│   ├── run_incremental.sh
│   ├── check_status.sh
│   ├── count_papers.sh
│   └── setup_crontab.sh
├── enrichment/               # Citation/abstract enrichment
│   └── run_enrichment.sh
├── resolution/               # Reference resolution (citation graph)
│   └── run_resolution.sh
└── maintenance/              # Deduplication, cleanup
    └── run_deduplication.sh
```

---

## Full Pipeline

Runs all 4 stages in sequence:

```bash
./scripts/run_full_pipeline.sh [OPTIONS]

Options:
  --since-year YEAR     Start year (default: 2020)
  --include-workshops   Include ACL workshop papers
  --skip-collection     Skip data collection step
  --skip-dedup          Skip deduplication step
  --skip-enrichment     Skip enrichment step
  --skip-resolution     Skip resolution step
  --parallel N          Concurrent requests (default: 10)
```

**Example**: Run only post-processing (skip collection):
```bash
./scripts/run_full_pipeline.sh --skip-collection
```

---

## Crawler Scripts

### Full Collection
```bash
./scripts/crawler/run_full_collection.sh [OPTIONS]

Options:
  --since-year YEAR    Start year (default: 2020)
  --skip-openalex      Skip OpenAlex collection
  --skip-acl           Skip ACL Anthology collection
  --skip-dblp          Skip DBLP collection
```

### Incremental Collection
```bash
./scripts/crawler/run_incremental.sh
```
Collects papers from the current year only.

### Check Status
```bash
./scripts/crawler/check_status.sh
```

### Setup Cron Job (Weekly Full Pipeline)
```bash
# Install weekly cron job (Sunday 2 AM)
./scripts/crawler/setup_crontab.sh --install

# Custom schedule (e.g., daily at 3 AM)
CRON_SCHEDULE="0 3 * * *" ./scripts/crawler/setup_crontab.sh --install

# Show/remove
./scripts/crawler/setup_crontab.sh --show
./scripts/crawler/setup_crontab.sh --remove
```
Runs full pipeline (collection → dedup → enrichment → resolution) for current year.

---

## Enrichment Scripts

4-step enrichment: DOI lookup → Title lookup → PDF extraction → Abstracts

```bash
./scripts/enrichment/run_enrichment.sh [OPTIONS]

Options:
  --parallel N       Concurrent requests (default: 10)
  --batch-size N     Batch size for updates (default: 50)
  --skip-citations   Skip DOI-based citation enrichment
  --skip-title       Skip title-based citation enrichment
  --skip-pdf         Skip PDF reference extraction
  --skip-abstracts   Skip abstract enrichment
  --citations-only   Only enrich citations (skip abstracts)
  --abstracts-only   Only enrich abstracts
```

**Steps**:
1. DOI lookup - Papers WITH DOIs via OpenAlex
2. Title lookup - Papers WITHOUT DOIs via OpenAlex title search
3. PDF extraction - Papers still missing refs via GROBID (requires GROBID running)
4. Abstracts - Fill missing abstracts via OpenAlex

**GROBID Setup** (for PDF extraction):
```bash
# x86_64 (Intel/AMD)
docker run -d --rm --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0

# ARM64 (Apple Silicon)
docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64
docker run -d --rm --name grobid -p 8070:8070 grobid-arm64
```

---

## Resolution Scripts

Builds citation graph by resolving references to internal paper IDs:

```bash
./scripts/resolution/run_resolution.sh [OPTIONS]

Options:
  --step STEP      Run specific step: normalize, arxiv, internal, all
  --dry-run        Preview changes without applying
  --limit N        Limit papers to process (0 = unlimited)
```

**Steps**:
1. `normalize` - Fix identifier formats (e.g., `arXiv:arXiv:` → `arXiv:`)
2. `arxiv` - Resolve arXiv IDs to DOIs via OpenAlex
3. `internal` - Resolve all refs to internal Qdrant point IDs

---

## Maintenance Scripts

### Deduplication
```bash
./scripts/maintenance/run_deduplication.sh [OPTIONS]

Options:
  --dry-run    Preview duplicates without removing (default)
  --apply      Actually remove duplicates
```

---

## Environment Variables

Set these in `.env` or export before running:

```bash
export OPENALEX_EMAIL=your-email@example.com  # Required for polite pool
export QDRANT_URL=http://localhost:6333
export QDRANT_COLLECTION=lexicon_arxiv
```
