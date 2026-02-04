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

# Configure environment
cp .env.example .env
```

Edit `.env` with your settings:
```env
OPENALEX_EMAIL=your-email@example.com   # Required for polite pool (10 req/sec)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=lexicon_arxiv
```

---

## 3. Start Qdrant

```bash
# Run Qdrant container
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

# Verify it's running
curl http://localhost:6333/health
```

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

This runs all 4 stages:
1. **Collection** - Crawl papers from all sources
2. **Deduplication** - Remove cross-source duplicates
3. **Enrichment** - Add citations and abstracts via OpenAlex
4. **Resolution** - Build citation graph (resolve references to internal IDs)

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

# 8. Check final status
python -m src.cli.core_collect status
python -m src.cli.core_collect ref-stats
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

---

## Next Steps

After pipeline completion:

1. **Verify data quality**: `python -m src.cli.core_collect status`
2. **Check citation graph**: `python -m src.cli.core_collect ref-stats`
3. **Start API server**: `uvicorn app.main:app --reload`
