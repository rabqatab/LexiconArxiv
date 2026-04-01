# Embedding Pipeline

## 1. Overview

The embedding pipeline converts paper abstracts into dense and sparse vectors stored in Qdrant, enabling hybrid search (dense + BM25 with RRF fusion). It runs as an offline batch process after data collection and enrichment.

---

## 2. Model Choice: Qwen3-Embedding-8B

| Property | Value |
|----------|-------|
| Model | `qwen3-embedding:8b` via Ollama |
| Full dimension | 4096 |
| Target dimension | 1024 (via Matryoshka Representation Learning truncation) |
| Instruction-aware | Yes — prepends `"Retrieve academic papers: "` for retrieval quality |

The model is served locally by Ollama. Client-side MRL truncation (slice first 1024 dims) reduces storage and index size by 4x while retaining most retrieval quality.

### 2.1 Vector Configuration (9 Dense + BM25)

The collection uses 9 dense named vectors plus 1 BM25 sparse vector. Title text is included in all dense vectors for improved retrieval.

| Named Vector | Description |
|-------------|-------------|
| `abstract-qwen3-8b` | Full abstract text |
| `structured-abstract` | Section-prefixed with multi-label dedup (e.g., `[TASK,APPROACH] sentence`) |
| `section-task` | Sentences labeled as task descriptions |
| `section-method` | Sentences labeled as method descriptions |
| `section-result` | Sentences labeled as results |
| `section-background` | Sentences labeled as background/related work |
| `section-approach` | Sentences labeled as approach details |
| `section-domain` | Sentences labeled as domain context |
| `section-contribution` | Sentences labeled as contributions |
| `bm25` (sparse) | BM25 sparse via `qdrant/bm25` on title + abstract |

All 9 dense vectors are 1024-dimensional (Qwen3-Embedding-8B with MRL truncation) using cosine distance.

---

## 3. Collection Migration

The original Qdrant collection (`lexicon_arxiv`) was payload-only — points had metadata but no vector configuration. Embedding requires a collection with named vector configs.

### Why migration is needed

Qdrant does not allow adding vector configs to an existing collection. A new collection must be created with the correct schema, then points are copied over.

### How it works

`CollectionMigrator` performs these steps:

1. **Snapshot** the old collection (backup)
2. **Create** new collection (`lexicon_arxiv_v2`) with vector configs:
   - `abstract-qwen3-8b`: dense, 1024d, cosine distance
   - `bm25`: sparse, IDF modifier (for server-side BM25)
3. **Scroll and copy** all points (payload only, no vectors yet)
4. Optionally **delete** the old collection
5. **Verify** counts match

After migration, update `QDRANT_COLLECTION` in `.env` to point to the new collection.

### CLI

```bash
# Dry run — show point count
uv run python -m src.cli.core_collect migrate-collection --dry-run

# Run migration
uv run python -m src.cli.core_collect migrate-collection

# Or via shell script
bash scripts/embedding/migrate_collection.sh
```

---

## 4. Batch Embedding Pipeline

The `PaperEmbedder` class embeds abstracts in batches and writes vectors to Qdrant using `update_vectors()` (not `upsert`), which attaches vectors to existing points without overwriting payloads.

### Pipeline steps

1. **Scroll** papers that lack a dense vector (`HasVectorCondition` skip for resume)
2. **Batch** abstracts (default 32 per request)
3. **Call Ollama** `/api/embed` with the batch
4. **Truncate** from 4096d to 1024d (MRL)
5. **Write** both dense and BM25 vectors via `update_vectors()`:
   - Dense: the truncated float vector
   - BM25: `Document(text=abstract, model="qdrant/bm25")` — Qdrant infers the sparse vector server-side

### Resume support

The pipeline is resume-safe. On each scroll, it uses Qdrant's `HasVectorCondition` to skip points that already have the `abstract-qwen3-8b` vector. This means interrupted runs can be restarted without re-embedding completed papers.

### CLI

```bash
# Default: batch_size=32, concurrency=4, resume=true
uv run python -m src.cli.core_collect embed-papers

# Higher throughput
uv run python -m src.cli.core_collect embed-papers --batch-size 64 --concurrency 8

# Limit to N papers (useful for testing)
uv run python -m src.cli.core_collect embed-papers --limit 100

# Restart from scratch (re-embed all)
uv run python -m src.cli.core_collect embed-papers --no-resume

# Or via shell script
bash scripts/embedding/run_embedding.sh
```

---

## 5. Server-side BM25

BM25 sparse vectors are computed by Qdrant itself using the `qdrant/bm25` built-in model. During embedding, each paper's abstract is passed as a `Document(text=..., model="qdrant/bm25")` alongside the dense vector. Qdrant tokenizes and indexes the text server-side — no client-side sparse encoding is needed.

At query time, the same mechanism is used: the search query is wrapped in a `Document` and sent as a BM25 prefetch leg alongside the dense prefetch.

---

## 6. Performance

Measured on NVIDIA DGX Spark (Grace Blackwell GB10):

| Metric | Value |
|--------|-------|
| Throughput | ~10 papers/sec (batch_size=32, concurrency=4) |
| Model load time | ~15s (first request) |
| Memory (Ollama) | ~6 GB VRAM |

Throughput scales with `--concurrency` up to GPU saturation.

---

## 7. File Reference

| File | Description |
|------|-------------|
| `src/core/embedding/embedder.py` | `PaperEmbedder` — batch embed + update_vectors |
| `src/core/embedding/migration.py` | `CollectionMigrator` — payload-only to named-vector migration |
| `src/cli/commands/embedding.py` | CLI commands: `embed-papers`, `migrate-collection` |
| `src/core/constants.py` | Model name, vector name, dimensions |
| `scripts/embedding/run_embedding.sh` | Shell wrapper for embedding |
| `scripts/embedding/migrate_collection.sh` | Shell wrapper for migration |

---

## Related Documents

- [Architecture Overview](../architecture/overview.md)
- [Search Pipeline](./search.md)
- [Data Collection](./data_collection.md)
