# CLI Reference

Complete reference for all CLI commands in LexiconArxiv.

---

## Quick Reference

```bash
# Full pipeline (recommended)
./scripts/run_full_pipeline.sh --since-year 2018 --include-workshops

# Or step by step
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020
uv run python -m src.cli.core_collect deduplicate
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10
uv run python -m src.cli.core_collect resolve-refs
uv run python -m src.cli.core_collect extract-keywords
```

---

## Storage Commands

### init-storage

Initialize Qdrant collection with proper schema.

```bash
uv run python -m src.cli.core_collect init-storage
```

### status

Check collection status and statistics.

```bash
uv run python -m src.cli.core_collect status
```

### delete-old-collection

Delete an old Qdrant collection (e.g., after migration to a new vector-enabled collection).

```bash
# Preview (no --confirm flag = dry run)
uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v3

# Delete
uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v3 --confirm
```

**Options:**
| Option | Description |
|--------|-------------|
| `--collection` | Name of the collection to delete (required) |
| `--confirm` | Actually delete the collection (without this flag, only previews) |

---

## Collection Commands

### collect (OpenAlex)

Collect papers from OpenAlex by venue or tier.

```bash
# Single venue
uv run python -m src.cli.core_collect collect --venue neurips --since-year 2020

# By tier
uv run python -m src.cli.core_collect collect --tier 0 --since-year 2020

# All venues
uv run python -m src.cli.core_collect collect --all --since-year 2020

# Count only (dry run)
uv run python -m src.cli.core_collect collect --all --count-only
```

### collect-acl

Collect papers from ACL Anthology.

```bash
# Single venue
uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2020

# All main venues
uv run python -m src.cli.core_collect collect-acl --all

# Include workshops
uv run python -m src.cli.core_collect collect-acl --all --include-workshops

# Workshops only
uv run python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024
```

### collect-dblp

Collect papers from DBLP (includes ACM venues: KDD, SIGIR, WWW, RecSys, CIKM, WSDM).

```bash
# Single venue
uv run python -m src.cli.core_collect collect-dblp --venue icail --since-year 2020

# All DBLP venues
uv run python -m src.cli.core_collect collect-dblp --all

# ACM venues only
uv run python -m src.cli.core_collect collect-dblp --all --acm-only
```

### collect-openreview

Collect papers from OpenReview (ICLR, NeurIPS, ICML).

```bash
# Single venue
uv run python -m src.cli.core_collect collect-openreview --venue iclr --since-year 2020

# All venues
uv run python -m src.cli.core_collect collect-openreview --all

# Include rejected papers
uv run python -m src.cli.core_collect collect-openreview --venue iclr --include-rejected
```

### collect-aaai

Collect papers from AAAI OJS (2020-2023).

```bash
# AAAI papers
uv run python -m src.cli.core_collect collect-aaai --venue aaai --since-year 2020

# All AAAI venues
uv run python -m src.cli.core_collect collect-aaai --all
```

### collect-all-sources

Collect from all sources in optimal order (OpenAlex, ACL, DBLP, OpenReview, AAAI).
DBLP collection includes all ACM venues.

```bash
# Standard collection
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# Include workshops
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Skip specific sources
uv run python -m src.cli.core_collect collect-all-sources --skip-openalex
uv run python -m src.cli.core_collect collect-all-sources --skip-acl --skip-dblp
```

### collect-incremental

Incremental collection for daily cron jobs.

```bash
# Daily cron job (papers updated in last 24 hours)
uv run python -m src.cli.core_collect collect-incremental

# Weekly catch-up
uv run python -m src.cli.core_collect collect-incremental --days 7

# Only specific source
uv run python -m src.cli.core_collect collect-incremental --source openalex
uv run python -m src.cli.core_collect collect-incremental --source openreview
```

**Crontab example (daily at 2 AM):**
```bash
0 2 * * * cd /path/to/project && uv run python -m src.cli.core_collect collect-incremental >> /var/log/lexicon_cron.log 2>&1
```

---

## Deduplication Commands

### deduplicate

Remove duplicate papers across sources.

```bash
# Preview duplicates
uv run python -m src.cli.core_collect deduplicate --dry-run

# Remove duplicates
uv run python -m src.cli.core_collect deduplicate

# Specific collection
uv run python -m src.cli.core_collect deduplicate --collection my_collection
```

### dedup-cleanup

Remove duplicates already in the corpus. Scrolls all non-stub papers, groups by DOI (or OpenAlex ID when no DOI), and for each group keeps the richest paper (has abstract/keywords/vectors), deleting the rest. Use this to clean up duplicates that slipped past collection-time dedup; `deduplicate` prevents them, `dedup-cleanup` removes existing ones.

```bash
# Preview duplicate groups
uv run python -m src.cli.core_collect dedup-cleanup --dry-run

# Remove duplicates
uv run python -m src.cli.core_collect dedup-cleanup
```

---

## Enrichment Commands

### enrich-1-refs-and-abstracts-by-doi-via-openalex

Fetch citation data from OpenAlex for papers with DOIs.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --dry-run

# Sequential
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex

# Parallel (recommended)
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10

# With limit
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --limit 1000
```

### enrich-3-refs-and-abstracts-by-title-via-openalex

Enrich papers without DOIs using title search. Matches titles against OpenAlex using normalized `SequenceMatcher` similarity (threshold ≥ 0.90).

```bash
uv run python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --parallel 5
```

### reset-title-enriched

Reset all title-enriched papers so they can be re-matched with the current matching logic. Clears DOI, referenced_works, and abstract for previously enriched papers and removes them from title and abstracts checkpoints.

```bash
# Preview
uv run python -m src.cli.core_collect reset-title-enriched --dry-run

# Reset
uv run python -m src.cli.core_collect reset-title-enriched
```

### enrich-6-abstracts-by-doi-via-openalex

Fetch missing abstracts from OpenAlex.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --dry-run

# Run
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10
```

### enrich-4-refs-by-doi-via-s2

Enrich using Semantic Scholar (fallback). Supports multi-key rotation via `S2_API_KEYS` (comma-separated); keys are rotated round-robin with per-key rate limiting.

```bash
# By DOI
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel 3

# By title (for papers without DOIs)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title

# Target specific venues
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title -v "NeurIPS 2024 poster"

# Prioritize recently collected papers (e.g., last 30 days)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --recent-days 30
```

**Options:**
| Option | Description |
|--------|-------------|
| `--by-title` | Search by title instead of DOI |
| `-v, --venue` | Filter by venue (repeatable) |
| `--min-refs N` | Minimum references for title match |
| `--recent-days N` | Prioritize papers collected within the last N days |
| `-n, --limit N` | Max papers to process |
| `-p, --parallel N` | Concurrent requests |

### enrich-2-refs-by-doi-via-crossref

Enrich papers with references from CrossRef (excellent for ACM/Springer papers).

```bash
# Preview
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --dry-run

# Enrich all papers with DOIs
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref

# Limit papers
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --limit 500

# Adjust concurrency (default: 5)
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel 20
```

**Note:** CrossRef has 97% success rate for ACM papers where Semantic Scholar fails. For polite pool access, set `CROSSREF_EMAIL` env var.

### enrich-8-metadata-by-stub-via-openalex

Enrich stub papers (external references) with metadata.

```bash
# Enrich top 100 most-cited stubs
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex

# Enrich DOI stubs only
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --limit 1000 --type doi

# Only highly-cited stubs (5+ citations)
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --min-citations 5

# Preview
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --dry-run
```

**Options:**
| Option | Description |
|--------|-------------|
| `--type [doi\|arxiv\|openalex]` | Filter by identifier type |
| `--min-citations N` | Only stubs cited N+ times |
| `-n, --limit N` | Max stubs to enrich |
| `-p, --parallel N` | Concurrent API requests |

### enrich-5-refs-by-pdf-via-grobid

Extract references from PDFs using GROBID. ACM papers (`10.1145/` DOIs) are automatically downloaded via a stealth headless browser that clears Cloudflare's JS challenge; all other publishers use the fast httpx path.

```bash
# Start GROBID first
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

# Preview
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --dry-run

# Run
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel 2

# ACM only (stealth browser, retry previous failures)
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid \
    --doi-prefix 10.1145/ --parallel 5 --retry-incomplete
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Count papers without extracting |
| `--limit N` | Max papers to process |
| `--batch-size N` | Papers per batch (default 50) |
| `--parallel N` | Concurrent extractions (default 20; use 5 for ACM) |
| `--venue TEXT` | Filter by venue name |
| `--doi-prefix TEXT` | Filter by DOI prefix (e.g. `10.1145/` for ACM) |
| `--retry-incomplete` | Clear checkpoint, re-process papers still missing refs |
| `--grobid-url URL` | GROBID server URL (default `http://localhost:8070`) |

### enrich-7-abstracts-by-pdf-via-grobid

Extract abstracts from PDFs via GROBID — a fallback for papers still missing abstracts after OpenAlex enrichment. Only processes papers with direct PDF URLs (ending in `.pdf`); requires a running GROBID server.

```bash
# Count papers needing PDF abstract extraction
uv run python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid --dry-run

# Extract abstracts
uv run python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid --parallel 5

# Target a specific venue
uv run python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid -v "PACLIC"
```

Options: `--dry-run`, `--limit N`, `--batch-size N`, `--parallel N`, `--venue TEXT`, `--grobid-url URL` (default `http://localhost:8070`).

### enrich-9-resolve-title-refs-via-openalex

Resolve `TITLE:xxx` references to proper `DOI:xxx`/`Wxxx` identifiers. When GROBID extracts a reference with only a title (no DOI/arXiv ID), it stores `TITLE:<title>` in `referenced_works`; this command searches OpenAlex and fuzzy-matches titles to resolve them, improving citation-graph completeness.

```bash
# Count papers with TITLE: refs
uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --dry-run

# Resolve all (parallel)
uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --parallel 5

# Re-process papers still missing data
uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --retry-incomplete
```

Options: `--dry-run`, `--limit N`, `--batch-size N`, `--delay FLOAT`, `--parallel N`, `--retry-incomplete`.

### enrich-10-code-repos

Find code repositories for papers via PWC Archive and HuggingFace Papers API.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-10-code-repos --dry-run

# Run with parallel requests
uv run python -m src.cli.core_collect enrich-10-code-repos --parallel 10

# With limit
uv run python -m src.cli.core_collect enrich-10-code-repos --limit 500
```

### enrich-11-code-repos-via-grobid

Extract GitHub URLs from paper PDFs using GROBID full-text extraction with section/context-based classification.

```bash
# Start GROBID first
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

# Preview
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --dry-run

# Run
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --parallel 5

# Custom GROBID URL
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --grobid-url http://myserver:8070
```

**Options:**
| Option | Description |
|--------|-------------|
| `--dry-run` | Count papers without extracting |
| `-n, --limit N` | Max papers to process |
| `-p, --parallel N` | Concurrent extractions (default: 5) |
| `--batch-size N` | Batch size (default: 20) |
| `--grobid-url URL` | GROBID server URL (default: `http://localhost:8070`) |
| `--retry-incomplete` | Re-process papers (clears checkpoint) |

### enrich-12-code-repos-via-github

Search GitHub API for code repositories matching papers. Two-tier strategy: Tier A (arXiv ID in README) and Tier B (title search with validation).

```bash
# Preview
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --dry-run

# Run
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --batch-size 50

# With limit
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --limit 200
```

**Options:**
| Option | Description |
|--------|-------------|
| `--dry-run` | Count papers without searching |
| `-n, --limit N` | Max papers to process |
| `--batch-size N` | Batch size (default: 50) |
| `--github-token` | Override `GITHUB_TOKEN` env var |
| `--retry-incomplete` | Re-process papers (clears checkpoint) |

**Rate Limits:** 30 search req/min with `GITHUB_TOKEN`, 10/min without.

---

## Reference Resolution Commands

### resolve-refs

Resolve reference identifiers to internal paper IDs.

```bash
# Full pipeline
uv run python -m src.cli.core_collect resolve-refs

# Dry run
uv run python -m src.cli.core_collect resolve-refs --dry-run

# Specific steps
uv run python -m src.cli.core_collect resolve-refs --step normalize
uv run python -m src.cli.core_collect resolve-refs --step arxiv
uv run python -m src.cli.core_collect resolve-refs --step internal

# With fuzzy matching
uv run python -m src.cli.core_collect resolve-refs --step internal --fuzzy-matching

# External search for unresolved titles
uv run python -m src.cli.core_collect resolve-refs --step internal --external-search

# Skip stub paper creation (stubs are created by default)
uv run python -m src.cli.core_collect resolve-refs --no-create-stubs
```

**Options:**
| Option | Description |
|--------|-------------|
| `--step [all\|normalize\|arxiv\|internal]` | Run specific step only |
| `--fuzzy-matching` | Use fuzzy title matching (slower) |
| `--external-search` | Search external APIs for unresolved titles |
| `--create-stubs/--no-create-stubs` | Create stub papers for unresolved references (default: enabled) |
| `-n, --limit N` | Max papers to process |
| `-p, --parallel N` | Concurrent requests |

### ref-stats

Show reference resolution statistics.

```bash
uv run python -m src.cli.core_collect ref-stats
```

### stub-stats

Show statistics about stub papers (external references).

```bash
# Summary view
uv run python -m src.cli.core_collect stub-stats

# Show top 50 most-cited stubs
uv run python -m src.cli.core_collect stub-stats --top 50

# JSON output
uv run python -m src.cli.core_collect stub-stats --json
```

---

## Citation Graph Commands

### build-cited-by

Build reverse citation index for GraphRAG.

```bash
uv run python -m src.cli.core_collect build-cited-by
```

### citation-graph-stats

Show citation graph statistics.

```bash
uv run python -m src.cli.core_collect citation-graph-stats
```

### build-citation-graph

Export citation graph to file.

```bash
# JSON format
uv run python -m src.cli.core_collect build-citation-graph -o graph.json

# GraphML format
uv run python -m src.cli.core_collect build-citation-graph -o graph.graphml --format graphml

# Streaming (low memory)
uv run python -m src.cli.core_collect build-citation-graph -o /tmp/graph --streaming
```

### analyze-citation-graph

Compute graph metrics (PageRank, HITS, etc.).

```bash
# All metrics
uv run python -m src.cli.core_collect analyze-citation-graph --all --top-n 50

# Compute and store PageRank
uv run python -m src.cli.core_collect analyze-citation-graph --compute-pagerank --store
```

### get-citing-papers

Get papers that cite a specific paper.

```bash
uv run python -m src.cli.core_collect get-citing-papers <paper_id>
```

### export-graph-subgraph

Export citation subgraph around a paper.

```bash
uv run python -m src.cli.core_collect export-graph-subgraph <paper_id> --hops 2 -o subgraph.json
```

---

## Keyword Extraction Commands

### extract-keywords

Extract keywords using regex + KeyBERT (default, no LLM). The `--llm/--judge` flags remain in the CLI for backward compatibility but are **deprecated at bulk scale** per Path B (2026-07-04): Ollama chat is retired from every pipeline stage, and the incremental runbook forbids them. See [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Ollama→vLLM policy.

```bash
# Default: regex + KeyBERT (production)
uv run python -m src.cli.core_collect extract-keywords

# Regex only (faster, no model loading)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Better embedding model for KeyBERT
uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

# Preview without saving
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Re-extract ALL papers (replace existing keywords)
uv run python -m src.cli.core_collect extract-keywords --force

# With limit
uv run python -m src.cli.core_collect extract-keywords --limit 1000

# Deprecated: LLM-first pipeline via Ollama (dev-laptop only; do NOT use in production/incremental)
uv run python -m src.cli.core_collect extract-keywords --llm --judge
```

**Options:**
| Option | Description |
|--------|-------------|
| `--dry-run` | Preview without saving |
| `--limit N` | Process max N papers |
| `--batch-size N` | Papers per batch (default: 100) |
| `--no-keybert` | Skip KeyBERT in fallback, use regex only |
| `--force` | Re-extract for papers with existing keywords |
| `--embedding-model` | Sentence-transformers model for KeyBERT fallback (default: `all-MiniLM-L6-v2`) |
| `--llm` | Enable LLM keyword extraction (Ollama) |
| `--judge` | Enable LLM judge validation (Ollama) |
| `--ollama-model` | Ollama model name (default: `granite4.1:8b`; fallback: `gemma4:e4b`) |
| `--ollama-timeout` | Ollama request timeout in seconds (default: 180) |

**Behavior:**
- Default: Skips papers that already have keywords
- With `--force`: Re-processes all papers, replacing existing keywords
- With `--llm` (deprecated at bulk scale): LLM is primary; regex + KeyBERT only run as fallback when LLM fails
- With `--llm` or `--judge`: Uses async execution

### keyword-stats

Show keyword extraction statistics.

```bash
# Summary view
uv run python -m src.cli.core_collect keyword-stats

# JSON output
uv run python -m src.cli.core_collect keyword-stats --json
```

### clear-keywords

Remove all keywords from corpus.

```bash
uv run python -m src.cli.core_collect clear-keywords --confirm
```

---

## Abstract Labeling Commands

### label-abstracts

Classify each sentence of a paper's abstract into 7 rhetorical roles: task, domain, background, approach, method, result, contribution. Results are stored in `abstract_structure`. **Production backend is vLLM + `ibm-granite/granite-4.1-8b`** per Path B (2026-07-04) — see [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) and [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md). Ollama chat is retired from every pipeline stage; the `--backend ollama` path is preserved as a dev-laptop fallback only.

```bash
# Preview (uses default backend)
uv run python -m src.cli.core_collect label-abstracts --dry-run --limit 5

# Production labeling via vLLM (requires serve_vllm.sh running — see vllm-labeling.md runbook)
uv run python -m src.cli.core_collect label-abstracts --backend vllm \
    --vllm-base-url http://localhost:8000 --vllm-max-concurrent 128

# Dev-laptop fallback: Ollama (~750 papers/hr — do NOT use for production/incremental)
uv run python -m src.cli.core_collect label-abstracts --backend ollama --limit 100

# Re-label papers that already have abstract_structure
uv run python -m src.cli.core_collect label-abstracts --backend vllm --force --limit 50
```

Options: `--backend {vllm|ollama}`, `--dry-run`, `--limit N`, `--batch-size N` (default 500), `--force`, `--vllm-model TEXT`, `--vllm-base-url URL`, `--vllm-max-concurrent INT`, `--ollama-model TEXT`, `--ollama-timeout FLOAT`.

---

## Embedding Commands

### migrate-collection

Migrate payload-only collection to vector-enabled (dense + BM25).

```bash
# Preview
uv run python -m src.cli.core_collect migrate-collection --dry-run

# Run migration
uv run python -m src.cli.core_collect migrate-collection

# Custom new collection name
uv run python -m src.cli.core_collect migrate-collection --new-collection my_collection_v2

# Delete old collection after migration
uv run python -m src.cli.core_collect migrate-collection --delete-old
```

**Options:**
| Option | Description |
|--------|-------------|
| `--new-collection` | Name for the new vector-enabled collection |
| `--delete-old` | Delete the old collection after successful migration |
| `--dry-run` | Preview migration without making changes |

### embed-papers

Embed paper abstracts with Qwen3-8B and BM25 sparse vectors.

```bash
# Preview
uv run python -m src.cli.core_collect embed-papers --dry-run

# Run with defaults
uv run python -m src.cli.core_collect embed-papers

# Custom concurrency and batch size
uv run python -m src.cli.core_collect embed-papers --batch-size 64 -p 8

# Limit number of papers
uv run python -m src.cli.core_collect embed-papers -n 1000

# Disable resume (start from scratch)
uv run python -m src.cli.core_collect embed-papers --no-resume
```

**Options:**
| Option | Description |
|--------|-------------|
| `--batch-size` | Number of papers per batch |
| `--concurrency`, `-p` | Concurrent embedding requests |
| `--limit`, `-n` | Max papers to embed |
| `--resume/--no-resume` | Resume from last checkpoint (default: resume) |
| `--dry-run` | Preview without embedding |
| `--consume-snapshot-queue` | Drain points queued by P2/P3 first, then fall through to default scroll |

### compute-topics

Compute UMAP + HDBSCAN topic clusters from paper embeddings.

```bash
# Preview
uv run python -m src.cli.core_collect compute-topics --dry-run

# Run with defaults
uv run python -m src.cli.core_collect compute-topics

# Custom clustering parameters
uv run python -m src.cli.core_collect compute-topics --min-cluster-size 50 --min-samples 10
```

**Options:**
| Option | Description |
|--------|-------------|
| `--min-cluster-size` | Minimum cluster size for HDBSCAN |
| `--min-samples` | Minimum samples for HDBSCAN |
| `--dry-run` | Preview without computing |

### compute-similarity

Compute precomputed semantic similarity edges between papers using section-level vectors. Produces 5 edge types: `same_method`, `same_task`, `same_result`, `method_transfer`, and `overall`.

```bash
# Preview
uv run python -m src.cli.core_collect compute-similarity --dry-run

# Run with defaults
uv run python -m src.cli.core_collect compute-similarity

# Custom k neighbors and batch size
uv run python -m src.cli.core_collect compute-similarity --k 20 --batch-size 128

# Limit number of papers
uv run python -m src.cli.core_collect compute-similarity --limit 5000
```

**Options:**
| Option | Description |
|--------|-------------|
| `--k` | Number of nearest neighbors per edge type |
| `--batch-size` | Papers per batch |
| `--limit` | Max papers to process |
| `--dry-run` | Preview without computing |

**Shell script wrapper:**
```bash
scripts/analytics/run_similarity.sh
```

---

## Snapshot Commands

Quarterly bootstrap + daily live-mode enrichment from a local OpenAlex `works`
snapshot. See [`docs/runbooks/snapshot-bootstrap.md`](../runbooks/snapshot-bootstrap.md)
for the full Day 0..11+ procedure.

All commands accept `--snapshot-dir` (default
`/mnt/nfs/ssd2/openalex_snapshot/data/works`), `--dry-run`,
`--resume/--no-resume`, and `--limit-files`. Per-phase checkpoints land in
`${DAGSTER_HOME:-$HOME/dagster_home}/snapshot_checkpoints/{p1,p2,p3,p4}/`.

### enrich-corpus-fields (P1)

Fill missing metadata fields on every matched corpus paper. Idempotent
(fill-only-missing). No corpus growth.

```bash
# Dry-run on 5 files
uv run python -m src.cli.core_collect enrich-corpus-fields --dry-run --limit-files 5

# Full bootstrap
uv run python -m src.cli.core_collect enrich-corpus-fields --resume
```

Expected duration: ≈6–9h on 596GB / 2127 .gz files.

### resolve-stubs-from-snapshot (P2)

Promote corpus stubs (identifier-only) to real papers when the snapshot has
matching records. `cited_by` is preserved across the promotion. Newly-promoted
papers with abstracts are queued for embedding.

```bash
# Dry-run sweep across thresholds (see runbook)
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
    --dry-run --resume --min-cites-per-year 5 --now-year 2026

# Full run with age-normalized citation gate (recommended)
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
    --min-cites-per-year 5 --now-year 2026
```

**Quality gate** (`--min-cites-per-year N`, default 0 = no filter): drops
promotion to ENRICH_KEEP_STUB when `cited_by_count / max(1, now - pub_year) < N`.
Self-normalizes recent vs old papers without bucket boundaries. See
[`docs/pipelines/stub-promotion.md`](../pipelines/stub-promotion.md#quality-gate---min-cites-per-year)
for the formula, worked examples, and recommended starting values.

**Options:**
| Option | Description |
|--------|-------------|
| `--min-cites-per-year FLOAT` | Age-normalized citation rate floor (default 0) |
| `--now-year INT` | Reference year for age calc (default current UTC year) |
| `--allow-promotion/--no-allow-promotion` | If False, only enrich-in-place |
| `--allow-merge/--no-allow-merge` | If False, refuse to merge into existing real paper |
| `--batch-size INT` | Upsert batch size (default 500) |

Expected duration: ≈24–30h.

### discover-corpus-gaps (P3)

Inject new AI-relevant papers from the snapshot via hybrid classification:
ANCHOR_INJECT (cited by ≥N corpus papers) + CONCEPT_INJECT (matches AI
taxonomy + age-scaled citation thresholds).

```bash
# Dry-run with cap to bound exploration
uv run python -m src.cli.core_collect discover-corpus-gaps \
    --dry-run --limit-files 30 --max-injections 5000

# Full run
uv run python -m src.cli.core_collect discover-corpus-gaps --resume
```

**Options:**
| Option | Description |
|--------|-------------|
| `--anchor-min-citers INT` | Min corpus papers citing this work to anchor-inject (default 2) |
| `--concept-min-recent INT` | Concept-inject threshold for papers ≤5y old (default 50) |
| `--concept-min-old INT` | Concept-inject threshold for older papers (default 200) |
| `--concept-min-year INT` | Recent/old boundary year (default 2018) |
| `--max-injections INT` | Stop early after N injections (safety cap) |

See [`docs/pipelines/corpus-gap-discovery.md`](../pipelines/corpus-gap-discovery.md)
for the AI taxonomy and threshold tuning. Expected duration: ≈4–8h depending
on `--max-injections`.

### extend-cited-by-from-snapshot (P4)

Compute `external_cited_by` for every corpus paper by scanning the snapshot
for works that reference it. Truncates each list at `--max-citers-per-paper`
(year DESC, cited_by_count DESC).

```bash
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot --resume
```

**Options:**
| Option | Description |
|--------|-------------|
| `--max-citers-per-paper INT` | Cap on external_cited_by list length (default 300) |

Expected duration: ≈2–3h.

### snapshot-live-delta

Run one live-mode pass: fetch yesterday's OpenAlex API delta and chain
P1→P2→P3→P4 per work (same phase logic as the bootstrap). Idempotent — same
`--since` is safe.

```bash
# Yesterday's delta
uv run python -m src.cli.core_collect snapshot-live-delta --days-back 1

# Explicit date with dry-run
uv run python -m src.cli.core_collect snapshot-live-delta --since 2026-06-22 --dry-run
```

**Options:**
| Option | Description |
|--------|-------------|
| `--days-back INT` | Fetch from N days ago (default 1) |
| `--since YYYY-MM-DD` | Explicit ISO date (overrides --days-back) |
| `--max-injections INT` | P3 safety cap |
| `--anchor-min-citers`, `--concept-min-*`, `--max-citers-per-paper` | Same as bootstrap CLIs |

Daily Dagster schedule `daily_snapshot_live_schedule` (cron `0 5 * * *` KST,
default STOPPED). Enable in the UI after bootstrap is stable. See
[`docs/pipelines/snapshot-live-mode.md`](../pipelines/snapshot-live-mode.md).

### snapshot-status

Print per-phase checkpoint progress + embedding queue depth.

```bash
uv run python -m src.cli.core_collect snapshot-status
```

### snapshot-reset

Reset a phase's checkpoint (destructive — clears done_files + last_summary +
failed_batches). **Preserves `quarantine.jsonl` audit trail** across resets.

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
```

**Options:**
| Option | Description |
|--------|-------------|
| `--phase {p1,p2,p3,p4}` | Phase to reset (required) |
| `--confirm` | Required to actually delete (without it, no-ops with warning) |

### snapshot-replay-failed

List items in a phase's `failed_batches/` directory (and optionally
`quarantine.jsonl`) for operator review. Does NOT auto-replay — operator must
manually re-run the phase after inspecting.

```bash
uv run python -m src.cli.core_collect snapshot-replay-failed --phase p2
uv run python -m src.cli.core_collect snapshot-replay-failed --phase p2 --quarantine
```

---

## Data Quality Commands

### data-quality

Show data quality report.

```bash
# Summary
uv run python -m src.cli.core_collect data-quality

# JSON output
uv run python -m src.cli.core_collect data-quality --json

# By venue breakdown
uv run python -m src.cli.core_collect data-quality --by-venue
```

---

## Venue Discovery Commands

### list-venues

List configured venues.

```bash
# All venues
uv run python -m src.cli.core_collect list-venues

# By tier
uv run python -m src.cli.core_collect list-venues --tier 0
```

### list-acl-venues

List ACL Anthology venues.

```bash
uv run python -m src.cli.core_collect list-acl-venues
```

### list-dblp-venues

List DBLP venues.

```bash
uv run python -m src.cli.core_collect list-dblp-venues
```

### list-openreview-venues

List OpenReview venues.

```bash
uv run python -m src.cli.core_collect list-openreview-venues
```

### list-aaai-venues

List AAAI OJS venues.

```bash
uv run python -m src.cli.core_collect list-aaai-venues
```

### discover-sources

Discover OpenAlex Source IDs for venues.

```bash
# Single venue
uv run python -m src.cli.core_collect discover-sources --venue icml

# All venues
uv run python -m src.cli.core_collect discover-sources --all
```

---

## Checkpoint Commands

### clear-checkpoint

Clear collection checkpoint.

```bash
uv run python -m src.cli.core_collect clear-checkpoint
```

### clear-enrich-1-checkpoint

Clear checkpoint for enrich-1 (refs-and-abstracts-by-doi-via-openalex).

```bash
uv run python -m src.cli.core_collect clear-enrich-1-checkpoint
```

### clear-enrich-2-checkpoint

Clear checkpoint for enrich-2 (refs-by-doi-via-crossref).

```bash
uv run python -m src.cli.core_collect clear-enrich-2-checkpoint
```

### clear-enrich-3-checkpoint

Clear checkpoint for enrich-3 (refs-and-abstracts-by-title-via-openalex).

```bash
uv run python -m src.cli.core_collect clear-enrich-3-checkpoint
```

### clear-enrich-4-checkpoint

Clear checkpoint for enrich-4 (refs-by-doi-via-s2).

```bash
uv run python -m src.cli.core_collect clear-enrich-4-checkpoint
# Clear only DOI-based checkpoint
uv run python -m src.cli.core_collect clear-enrich-4-checkpoint --type doi
# Clear only title-based checkpoint
uv run python -m src.cli.core_collect clear-enrich-4-checkpoint --type title
```

### clear-enrich-5-checkpoint

Clear checkpoint for enrich-5 (refs-by-pdf-via-grobid).

```bash
uv run python -m src.cli.core_collect clear-enrich-5-checkpoint
```

### clear-enrich-6-checkpoint

Clear checkpoint for enrich-6 (abstracts-by-doi-via-openalex).

```bash
uv run python -m src.cli.core_collect clear-enrich-6-checkpoint
```

### clear-enrich-7-checkpoint

Clear checkpoint for enrich-7 (abstracts-by-pdf-via-grobid).

```bash
uv run python -m src.cli.core_collect clear-enrich-7-checkpoint
```

### clear-enrich-9-checkpoint

Clear checkpoint for enrich-9 (resolve-title-refs-via-openalex).

```bash
uv run python -m src.cli.core_collect clear-enrich-9-checkpoint
```

### clear-enrich-10-checkpoint

Clear checkpoint for enrich-10 (code-repos via PWC/HuggingFace).

```bash
uv run python -m src.cli.core_collect clear-enrich-10-checkpoint
```

### clear-enrich-11-checkpoint

Clear checkpoint for enrich-11 (code-repos-via-grobid).

```bash
uv run python -m src.cli.core_collect clear-enrich-11-checkpoint
```

### clear-enrich-12-checkpoint

Clear checkpoint for enrich-12 (code-repos-via-github).

```bash
uv run python -m src.cli.core_collect clear-enrich-12-checkpoint
```

### clear-resolve-checkpoint

Clear reference resolution checkpoint.

```bash
# All steps
uv run python -m src.cli.core_collect clear-resolve-checkpoint

# Specific step
uv run python -m src.cli.core_collect clear-resolve-checkpoint --step normalize
```

### clear-keyword-checkpoint

Clear keyword extraction checkpoint.

```bash
uv run python -m src.cli.core_collect clear-keyword-checkpoint
```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENALEX_API_KEYS` | Comma-separated OpenAlex API keys for round-robin rotation | No |
| `OPENALEX_EMAIL` | Email for OpenAlex polite pool fallback (10 req/sec) | Yes |
| `QDRANT_URL` | Qdrant server URL | Yes |
| `QDRANT_API_KEY` | Qdrant API key (for cloud) | No |
| `S2_API_KEYS` | Semantic Scholar API keys (comma-separated for round-robin rotation with per-key rate limiting). Legacy `S2_API_KEY` (singular) still works. | No |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`). Used by `embed-papers` (bulk + incremental + search) and search-time HyDE. Per Path B (2026-07-04), Ollama chat is retired from every pipeline stage; production labeling runs on vLLM (see `VLLM_*` vars in `.env.example`). `GEMINI_API_KEYS` was removed in v0.12. | No |
| `VLLM_MODEL`, `VLLM_PORT`, `VLLM_GPU_MEM_UTIL`, `VLLM_MAX_MODEL_LEN`, `VLLM_IMAGE` | vLLM labeling backend configuration (containerized). See `.env.example` and [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md). | No |
| `GITHUB_TOKEN` | GitHub personal access token for code repo search (30 req/min vs 10/min) | No |
| `DAGSTER_HOME` | Holds per-phase snapshot checkpoints + embedding queue (default: `$HOME/dagster_home`) | No |

---

## See Also

- [Quick Start Guide](../guides/quickstart.md)
- [Crawling Guide](../guides/crawling.md)
- [Troubleshooting](../guides/troubleshooting.md)
