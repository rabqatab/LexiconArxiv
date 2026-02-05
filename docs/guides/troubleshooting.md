# Troubleshooting Guide

Solutions to common issues when running LexiconArxiv.

---

## Connection Issues

### Qdrant Connection Error

**Symptoms:**
- `Connection refused` errors
- `Failed to connect to Qdrant`

**Solutions:**

```bash
# Check if Qdrant is running
docker ps | grep qdrant

# Start Qdrant
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

# Restart if needed
docker restart qdrant

# Verify connection
curl http://localhost:6333/health
```

### GROBID Connection Error

**Symptoms:**
- PDF extraction fails
- `Connection refused on port 8070`

**Solutions:**

```bash
# Check if GROBID is running
curl http://localhost:8070/api/isalive

# Start GROBID (x86_64)
docker run -d --rm --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0

# For ARM64 (Apple Silicon) - see ARM64 section below
```

---

## Rate Limiting

### OpenAlex 429 Errors

**Symptoms:**
- `HTTP 429 Too Many Requests`
- Collection slows down significantly

**Solutions:**

1. Set `OPENALEX_EMAIL` in `.env` for polite pool access (10 req/sec vs 1 req/sec)
2. Collection includes automatic delays - just wait
3. If persistent, reduce parallelism:

```bash
python -m src.cli.core_collect enrich-citations --parallel 5
```

### Semantic Scholar Rate Limits

**Symptoms:**
- `Rate limit exceeded` from S2 API

**Solutions:**

1. Get an S2 API key: https://www.semanticscholar.org/product/api#api-key
2. Set `S2_API_KEY` in `.env`
3. Keep parallelism low:

```bash
python -m src.cli.core_collect enrich-s2 --parallel 3
```

---

## Collection Issues

### Resuming Failed Collections

Collections are checkpointed automatically. Simply re-run the same command:

```bash
# This will resume from where it left off
python -m src.cli.core_collect collect --all --since-year 2020
```

To start fresh:

```bash
python -m src.cli.core_collect clear-checkpoint
```

### OpenReview Returns 0 Papers

**Cause:** Wrong API version for the venue/year combination.

**API Version Thresholds:**

| Venue | API v1 | API v2 |
|-------|--------|--------|
| ICLR | 2013-2023 | 2024+ |
| NeurIPS | 2019-2022 | 2023+ |
| ICML | N/A | 2023+ only |

The collector automatically selects the correct API version. If issues persist:

1. Check year is within supported range
2. Verify network connectivity to both `api.openreview.net` and `api2.openreview.net`

### ACL Anthology XML Parse Errors

**Symptoms:**
- `XML parsing failed`
- Missing papers from ACL venues

**Solutions:**

1. ACL Anthology XML files are fetched from GitHub - check network
2. Some older XML files have encoding issues - report to ACL Anthology

---

## Memory Issues

### Out of Memory During Collection

**Cause:** Deduplicator keeps papers in memory.

**Solutions:**

1. Collect venue-by-venue instead of all at once:

```bash
python -m src.cli.core_collect collect --venue neurips --since-year 2020
python -m src.cli.core_collect collect --venue icml --since-year 2020
```

2. Restart Python between venues (clears deduplicator memory)

### Out of Memory During Enrichment

**Solutions:**

Reduce parallelism:

```bash
python -m src.cli.core_collect enrich-citations --parallel 5
```

---

## ARM64 (Apple Silicon) Issues

### GROBID `exec format error`

**Symptoms:**
```
exec format error
# or
UnsatisfiedLinkError: libwapiti.so
```

**Cause:** Official GROBID Docker image is x86_64 only.

**Solution:** Build ARM64 image from source:

```bash
docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64
docker run -d --rm --name grobid -p 8070:8070 grobid-arm64
```

See `docker/grobid-arm64/grobid_arm64_troubleshooting.md` for details.

---

## Data Quality Issues

### Low Citation Coverage

**Symptoms:**
- `ref-stats` shows low resolution rate
- Many papers missing `referenced_works`

**Solutions:**

Run the full enrichment pipeline:

```bash
# 1. OpenAlex (best for papers with DOIs)
python -m src.cli.core_collect enrich-citations --parallel 10

# 2. By title (for papers without DOIs)
python -m src.cli.core_collect enrich-citations-by-title --parallel 5

# 3. Semantic Scholar fallback
python -m src.cli.core_collect enrich-s2 --parallel 3

# 4. PDF extraction (last resort)
python -m src.cli.core_collect extract-pdf-refs --parallel 2
```

### Missing Abstracts

**Cause:** DBLP papers have no abstracts.

**Solution:**

```bash
python -m src.cli.core_collect enrich-abstracts --parallel 10
```

### Duplicate Papers

**Symptoms:**
- Same paper appears multiple times in search results
- `status` shows more papers than expected

**Solution:**

```bash
# Preview duplicates
python -m src.cli.core_collect deduplicate --dry-run

# Remove duplicates
python -m src.cli.core_collect deduplicate
```

---

## Checkpoint Issues

### Checkpoint Corrupted

**Symptoms:**
- `JSON decode error` when resuming
- Collection starts from wrong point

**Solution:**

Clear the relevant checkpoint:

```bash
# Collection checkpoint
python -m src.cli.core_collect clear-checkpoint

# Enrichment checkpoints
python -m src.cli.core_collect clear-enrichment-checkpoint
python -m src.cli.core_collect clear-enrichment-checkpoint --type abstracts

# Resolution checkpoint
python -m src.cli.core_collect clear-resolve-checkpoint

# Keyword checkpoint
python -m src.cli.core_collect clear-keyword-checkpoint
```

---

## Keyword Extraction Issues

### KeyBERT Import Error

**Symptoms:**
- `ModuleNotFoundError: No module named 'keybert'`

**Solution:**

Install KeyBERT dependencies:

```bash
pip install keybert sentence-transformers
# or
uv pip install keybert sentence-transformers
```

### Slow Keyword Extraction

**Cause:** KeyBERT uses ML model for each paper.

**Solutions:**

1. Use regex-only mode (faster):

```bash
python -m src.cli.core_collect extract-keywords --no-keybert
```

2. Limit batch size:

```bash
python -m src.cli.core_collect extract-keywords --limit 1000
```

---

## Getting Help

If issues persist:

1. Check logs in `logs/` directory
2. Run with verbose output: add `--verbose` flag
3. Report issues at: https://github.com/your-org/lexiconarxiv/issues

---

## See Also

- [Quick Start Guide](./quickstart.md)
- [Crawling Guide](./crawling.md)
- [CLI Reference](../reference/cli.md)
