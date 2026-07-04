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

# Start Qdrant (with persistent volume)
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant

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

### Qdrant Connection Reset During build_cited_by

**Symptoms:**
- `Connection reset by peer` error
- `httpx.ReadError: [Errno 104] Connection reset by peer`
- Crash during Stage 5 (Graph) of the pipeline

**Cause:**
The `build_cited_by` command makes 100k+ individual API calls to Qdrant, which can overwhelm the connection pool.

**Solutions:**

1. **Use the latest code** (v0.7.2+) which includes retry logic and batching:
   ```bash
   git pull
   uv run python -m src.cli.core_collect build-cited-by
   ```

2. **If still failing**, restart Qdrant and retry:
   ```bash
   docker restart qdrant
   sleep 5
   uv run python -m src.cli.core_collect build-cited-by
   ```

3. **For persistent issues**, increase Qdrant resources:
   ```bash
   # Restart with more memory
   docker stop qdrant && docker rm qdrant
   docker run -d --name qdrant -p 6333:6333 \
     --memory=4g \
     -v qdrant_storage:/qdrant/storage \
     qdrant/qdrant
   ```

---

## Rate Limiting

### OpenAlex 429 Errors

**Symptoms:**
- `HTTP 429 Too Many Requests`
- Collection slows down significantly
- Repeated "Rate limited, waiting 60s..." messages

**Cause:**
OpenAlex free API key credits reset daily. When exhausted, all requests return 429 until the next reset (midnight UTC / 09:00 KST).

**Solutions:**

1. Use multiple API keys: set `OPENALEX_API_KEYS=key1,key2,key3` in `.env` for round-robin rotation across keys
2. Set `OPENALEX_EMAIL` in `.env` as fallback polite pool (10 req/sec vs 1 req/sec)
3. The system automatically rotates to the next key when one is exhausted, and falls back to email when all keys are exhausted
4. Exhausted keys re-enter rotation after a 5-minute cooldown
5. Rate-limited retries are capped at 3 attempts before skipping and moving on
6. If persistent, reduce parallelism:

```bash
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 5
```

**Note:** Both the enrichment pipeline and the collection crawler share the same `OpenAlexKeyManager` for multi-key rotation and automatic fallback.

### Semantic Scholar Rate Limits

**Symptoms:**
- `Rate limit exceeded` from S2 API

**Solutions:**

1. Get an S2 API key: https://www.semanticscholar.org/product/api#api-key
2. Set `S2_API_KEY` in `.env`
3. Keep parallelism low:

```bash
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel 3
```

---

## Collection Issues

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
uv run python -m src.cli.core_collect collect --venue neurips --since-year 2020
uv run python -m src.cli.core_collect collect --venue icml --since-year 2020
```

2. Restart Python between venues (clears deduplicator memory)

### Out of Memory During Enrichment

**Solutions:**

Reduce parallelism:

```bash
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 5
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

### ACM PDF Download Failures (403 / Cloudflare)

**Symptoms:**
```
Error downloading https://doi.org/10.1145/...: Client error '403 Forbidden'
```

**Cause:** ACM Digital Library is behind Cloudflare bot protection. Anonymous httpx requests are blocked.

**Solution:** The pipeline automatically routes ACM DOIs (`10.1145/...`) through a stealth headless Chromium browser. Ensure Chromium is installed:

```bash
uv run crawl4ai-setup
# Or: uv run python -m playwright install chromium
```

If the browser can't start (missing Chromium binary), re-run setup. If Cloudflare starts blocking the stealth browser (evolving detection), the download will fail gracefully and return None — no pipeline crash.

For ACM-specific re-extraction:
```bash
./scripts/enrichment/enrich_acm_pdfs.sh --dry-run
```

### DBLP HTTP 500 Errors

**Symptoms:**
```
DBLP search failed for kdd after 4 attempts: 500
```

**Cause:** DBLP's search API returns transient 500s under load.

**Solution:** Automatic — the collector retries with exponential backoff (1s → 8s, 4 attempts). If all retries fail, the venue is skipped and other venues continue. Re-running the incremental will pick up the failed venue.

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
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10

# 2. By title (for papers without DOIs)
uv run python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --parallel 5

# 3. Semantic Scholar fallback
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel 3

# 4. PDF extraction (last resort)
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel 2
```

### Missing Abstracts

**Cause:** DBLP papers have no abstracts.

**Solution:**

```bash
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10
```

### Duplicate Papers

**Symptoms:**
- Same paper appears multiple times in search results
- `status` shows more papers than expected

**Solution:**

```bash
# Preview duplicates
uv run python -m src.cli.core_collect deduplicate --dry-run

# Remove duplicates
uv run python -m src.cli.core_collect deduplicate
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
uv run python -m src.cli.core_collect clear-checkpoint

# Enrichment checkpoints
uv run python -m src.cli.core_collect clear-enrich-1-checkpoint
uv run python -m src.cli.core_collect clear-enrich-6-checkpoint

# Resolution checkpoint
uv run python -m src.cli.core_collect clear-resolve-checkpoint

# Keyword checkpoint
uv run python -m src.cli.core_collect clear-keyword-checkpoint
```

---

## Keyword Extraction Issues

### KeyBERT Import Error

**Symptoms:**
- `ModuleNotFoundError: No module named 'keybert'`

**Solution:**

Install KeyBERT dependencies:

```bash
uv pip install keybert sentence-transformers
```

### Slow Keyword Extraction

**Cause:** KeyBERT uses ML model for each paper.

**Solutions:**

1. Use regex-only mode (faster):

```bash
uv run python -m src.cli.core_collect extract-keywords --no-keybert
```

2. Limit batch size:

```bash
uv run python -m src.cli.core_collect extract-keywords --limit 1000
```

### Ollama Connection Refused

**Symptoms:**
- `httpx.ConnectError: Connection refused` when running `embed-papers` (bulk + incremental + search), search-time HyDE, or the dev-fallback `label-abstracts --backend ollama` / `extract-keywords --llm` paths.

**Solution:**

1. Ensure Ollama is running:

```bash
ollama serve
```

2. Pull the required model for embedding:

```bash
ollama pull qwen3-embedding:8b   # embed-papers + search-time query embedding + HyDE
```

3. Verify with custom URL if not on default port:

```bash
OLLAMA_BASE_URL=http://localhost:11434 uv run python -m src.cli.core_collect embed-papers --dry-run
```

**Policy note (Path B, 2026-07-04):** Ollama chat is retired from every pipeline stage. Production labeling runs on **vLLM + `ibm-granite/granite-4.1-8b`** — see [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) and [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md). The Gemini backend was removed in v0.12; see `.env.example` for the current env-var set. Only `embed-papers` and search-time HyDE still hit Ollama.

### LLM Extraction Timeout

**Cause:** Local Ollama model is slower than the default 180s timeout (rare with the production models above; happens when running larger backups on constrained hardware).

**Solutions:**

1. Use a smaller / faster model:

```bash
uv run python -m src.cli.core_collect extract-keywords --llm --ollama-model qwen2.5:7b
```

2. Raise the timeout:

```bash
uv run python -m src.cli.core_collect extract-keywords --llm --ollama-timeout 300
```

---

## Data Loss Prevention

### Always Use Persistent Volumes

Running Qdrant **without** `-v` means all data lives inside the container. If the container is removed (`docker rm`), all data is permanently lost.

**Correct (persistent):**
```bash
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

**Dangerous (ephemeral):**
```bash
# DO NOT USE - data lost on docker rm!
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant
```

> **Note**: `docker restart qdrant` and `docker stop/start qdrant` are safe — they preserve container data. Only `docker rm` destroys it.

### Check if Your Container Has a Volume

```bash
docker inspect qdrant --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{end}}'
# Should show: /var/lib/docker/volumes/qdrant_storage/_data -> /qdrant/storage
# If empty, your data is at risk!
```

### Snapshot Backups

Use the snapshot script to back up your collection before risky operations:

```bash
# Create a snapshot (saved to data/backups/)
./scripts/maintenance/qdrant_snapshot.sh

# List existing snapshots
./scripts/maintenance/qdrant_snapshot.sh --list

# Restore from snapshot
./scripts/maintenance/qdrant_snapshot.sh --restore data/backups/lexicon_arxiv_2026-02-13_120000.snapshot
```

The full pipeline automatically creates a snapshot before running (disable with `--skip-snapshot`).

### Migrating to Persistent Volume

If your Qdrant is currently running without a volume:

1. **Create a snapshot first:**
   ```bash
   ./scripts/maintenance/qdrant_snapshot.sh
   ```

2. **Stop and remove the old container:**
   ```bash
   docker stop qdrant && docker rm qdrant
   ```

3. **Start with persistent volume:**
   ```bash
   docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant
   ```

4. **Restore from snapshot:**
   ```bash
   ./scripts/maintenance/qdrant_snapshot.sh --restore data/backups/<your-snapshot>.snapshot
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
