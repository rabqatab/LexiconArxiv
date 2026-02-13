# Quick Start Guide

Complete setup and pipeline execution from a fresh clone.

---

## 1. Prerequisites

- Python 3.11+
- Docker (for Qdrant)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

---

## 2. Setup

```bash
# Clone repository
git clone https://github.com/your-org/lexiconarxiv.git
cd lexiconarxiv

# Create virtual environment (using uv)
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Make all scripts executable
chmod +x scripts/**/*.sh

# Configure environment
cp .env.example .env
```

Edit `.env` with your settings:
```env
OPENALEX_EMAIL=your-email@example.com   # Required for polite pool (10 req/sec)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=lexicon_arxiv
```

### Deploying to a Production Server

After cloning on a new machine (or pulling updates):

```bash
git clone https://github.com/your-org/lexiconarxiv.git && cd lexiconarxiv
uv venv && source .venv/bin/activate && uv pip install -e .
chmod +x scripts/**/*.sh
cp .env.example .env  # then edit with your credentials
```

If pulling updates to an existing deployment, clean stale Python cache:

```bash
git pull && find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

---

## 3. Start Docker Services

```bash
# Run Qdrant (vector database)
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant

# Run GROBID (PDF reference extraction) - optional but recommended
# For x86_64 (Intel/AMD):
docker run -d --rm --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0

# For ARM64 (Apple Silicon, ARM Linux) - build from source:
docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64
docker run -d --rm --name grobid -p 8070:8070 grobid-arm64

# Verify they're running
curl http://localhost:6333/health
curl http://localhost:8070/api/isalive
```

> **Note**: GROBID is optional. If not running, the pipeline will skip PDF extraction and only use OpenAlex for reference enrichment.

---

## 4. Initialize Storage

```bash
python -m src.cli.core_collect init-storage
```

---

## 5. Run Full Pipeline

### Option A: Single Command (Recommended)

```bash
./scripts/run_full_pipeline.sh --since-year 2018 --include-workshops
```

This runs all 5 stages:
1. **Collection** - Crawl papers from all sources
2. **Deduplication** - Remove cross-source duplicates
3. **Enrichment** - Add citations and abstracts via OpenAlex
4. **Resolution** - Build citation graph (resolve references to internal IDs)
5. **Keyword Extraction** - Extract acronyms and semantic keywords for BM25 search

### Option B: Step by Step

```bash
# 1. Collect from all sources (2018+)
python -m src.cli.core_collect collect-all-sources --since-year 2018 --include-workshops

# 2. Deduplicate
python -m src.cli.core_collect deduplicate

# 3. Enrich citations (papers WITH DOIs)
python -m src.cli.core_collect enrich-citations --parallel 10

# 4. Enrich citations by title (papers WITHOUT DOIs - e.g., OpenReview)
python -m src.cli.core_collect enrich-citations-by-title --parallel 5

# 5. Extract refs from PDFs (papers still missing refs - requires GROBID)
# Start GROBID first: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
python -m src.cli.core_collect extract-pdf-refs

# 6. Enrich abstracts
python -m src.cli.core_collect enrich-abstracts --parallel 10

# 7. Resolve references (build citation graph)
python -m src.cli.core_collect resolve-refs

# 8. Extract keywords (for BM25 search)
python -m src.cli.core_collect extract-keywords

# 9. Check final status
python -m src.cli.core_collect status
python -m src.cli.core_collect ref-stats
python -m src.cli.core_collect keyword-stats
```

---

## 6. Monitor Progress

```bash
# Check collection status
python -m src.cli.core_collect status

# Check reference resolution stats
python -m src.cli.core_collect ref-stats

# List venues
python -m src.cli.core_collect list-venues
```

---

## Estimated Scale

| Year Range | Papers (approx) |
|------------|-----------------|
| 2020-2025  | ~100K           |
| 2018-2025  | ~150K           |
| 2015-2025  | ~200K           |

By source (2018-2025):

| Source | Papers |
|--------|--------|
| OpenAlex (ML/AI/DM) | ~60K |
| ACL Anthology + Workshops | ~50K |
| OpenReview (ICLR, NeurIPS, ICML) | ~25K |
| ACM Digital Library | ~15K |
| DBLP | ~8K |
| AAAI OJS | ~10K |
| **Total (after dedup)** | **~100-150K** |

---

## Tips

### Resume Interrupted Collection

Collection is checkpointed. If interrupted, just re-run the same command:

```bash
# Will resume from last checkpoint
python -m src.cli.core_collect collect-all-sources --since-year 2018
```

### Clear Checkpoints

If you want to restart collection from scratch:

```bash
python -m src.cli.core_collect clear-checkpoint
```

### Collect Specific Sources Only

```bash
# OpenAlex only
python -m src.cli.core_collect collect --venue neurips --since-year 2018

# ACL Anthology only
python -m src.cli.core_collect collect-acl --all --include-workshops --since-year 2018

# OpenReview only
python -m src.cli.core_collect collect-openreview --all --since-year 2018
```

### Skip Stages in Full Pipeline

```bash
# Skip collection (run only postprocessing)
./scripts/run_full_pipeline.sh --skip-collection

# Skip enrichment
./scripts/run_full_pipeline.sh --skip-enrichment
```

### Keyword Extraction Options

```bash
# Preview without saving
python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Regex-only extraction (faster, no KeyBERT model loading)
python -m src.cli.core_collect extract-keywords --no-keybert

# Re-extract ALL papers (replace existing keywords)
python -m src.cli.core_collect extract-keywords --force

# Custom batch size
python -m src.cli.core_collect extract-keywords --batch-size 200
```

By default, papers with existing keywords are skipped. Use `--force` to re-extract.

See [Keyword Extraction Pipeline](../pipelines/keyword_extraction.md) for detailed documentation.

---

## Troubleshooting

### Qdrant Connection Error

```bash
# Check if Qdrant is running
docker ps | grep qdrant

# Restart if needed
docker restart qdrant
```

### Rate Limiting (OpenAlex)

Make sure `OPENALEX_EMAIL` is set in `.env` for polite pool access (10 req/sec vs 1 req/sec).

### Out of Memory

Reduce parallelism:
```bash
python -m src.cli.core_collect enrich-citations --parallel 5
```

### GROBID on ARM64 (Apple Silicon)

The official GROBID image is x86_64 only. On ARM64, you'll see:
```
exec format error
# or
UnsatisfiedLinkError: libwapiti.so
```

**Solution**: Build ARM64 image from source:
```bash
docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64
docker run -d --rm --name grobid -p 8070:8070 grobid-arm64
```

See `docker/grobid-arm64/grobid_arm64_troubleshooting.md` for details.

---

## 7. Incremental Updates (Weekly Cron Job)

After initial collection, set up automated weekly updates:

### Setup Cron Job

```bash
# Install weekly cron job (runs every Sunday at 2 AM)
./scripts/crawler/setup_crontab.sh --install

# Or customize schedule (e.g., daily at 3 AM)
CRON_SCHEDULE="0 3 * * *" ./scripts/crawler/setup_crontab.sh --install

# Check installed cron
./scripts/crawler/setup_crontab.sh --show

# Remove cron job
./scripts/crawler/setup_crontab.sh --remove
```

The cron job runs the full pipeline for **current year only**:
1. Collection - Crawl new papers from all sources
2. Deduplication - Remove cross-source duplicates
3. Enrichment - Add citations/abstracts via OpenAlex + GROBID
4. Resolution - Build citation graph

Logs are saved to `logs/incremental_pipeline.log`.

### Manual Incremental Run

```bash
# Run full pipeline for current year only
./scripts/run_full_pipeline.sh --since-year 2026 --include-workshops

# Or just post-processing (if collection already done)
./scripts/run_full_pipeline.sh --skip-collection
```

---

## Next Steps

After pipeline completion:

1. **Verify data quality**: `python -m src.cli.core_collect status`
2. **Check citation graph**: `python -m src.cli.core_collect ref-stats`
3. **Check keyword coverage**: `python -m src.cli.core_collect keyword-stats`
4. **Start API server**: `uvicorn app.main:app --reload`

---

## See Also

- [CLI Reference](../reference/cli.md) - Complete CLI command reference
- [Keyword Extraction Pipeline](../pipelines/keyword_extraction.md) - Keyword/acronym extraction details
- [Data Model](../architecture/data_model.md) - Qdrant schema and payload fields
- [Troubleshooting Guide](./troubleshooting.md) - Common issues and solutions
