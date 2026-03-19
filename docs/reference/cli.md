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
uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v1

# Delete
uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v1 --confirm
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

Enrich using Semantic Scholar (fallback).

```bash
# By DOI
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel 3

# By title (for papers without DOIs)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title

# Target specific venues
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title -v "NeurIPS 2024 poster"
```

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

Extract references from PDFs using GROBID.

```bash
# Start GROBID first
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

# Preview
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --dry-run

# Run
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel 2
```

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

Extract keywords using an LLM-first pipeline with regex + KeyBERT as fallback, and optional LLM judge validation.

```bash
# LLM-first pipeline with Gemini + judge (recommended)
uv run python -m src.cli.core_collect extract-keywords --llm --judge

# LLM-first with local Ollama
uv run python -m src.cli.core_collect extract-keywords --llm --judge --llm-backend ollama

# Fallback only: regex + KeyBERT (no LLM)
uv run python -m src.cli.core_collect extract-keywords

# Regex only (faster, no model loading)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Better embedding model for KeyBERT fallback
uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

# Preview without saving
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Re-extract ALL papers (replace existing keywords)
uv run python -m src.cli.core_collect extract-keywords --force

# With limit
uv run python -m src.cli.core_collect extract-keywords --limit 1000

# Custom batch size
uv run python -m src.cli.core_collect extract-keywords --batch-size 200
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
| `--llm` | Enable LLM keyword extraction (primary) |
| `--llm-backend` | LLM backend: `gemini` (default) or `ollama` |
| `--judge` | Enable LLM judge validation |
| `--judge-backend` | Judge backend: `gemini` or `ollama` (default: same as `--llm-backend`) |
| `--ollama-model` | Ollama model name (default: `llama3.1:8b`) |
| `--gemini-model` | Gemini model name (default: `gemini-3-flash-preview`) |

**Behavior:**
- Default: Skips papers that already have keywords
- With `--force`: Re-processes all papers, replacing existing keywords
- With `--llm`: LLM is primary; regex + KeyBERT only run as fallback when LLM fails
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
| `S2_API_KEY` | Semantic Scholar API key | No |
| `GEMINI_API_KEYS` | Gemini API key(s), comma-separated for round-robin (keywords + labeling) | No |
| `GEMINI_API_KEY` | Fallback for `GEMINI_API_KEYS` (singular) | No |
| `GOOGLE_API_KEY` | Fallback (legacy) | No |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) | No |
| `GITHUB_TOKEN` | GitHub personal access token for code repo search (30 req/min vs 10/min) | No |

---

## See Also

- [Quick Start Guide](../guides/quickstart.md)
- [Crawling Guide](../guides/crawling.md)
- [Troubleshooting](../guides/troubleshooting.md)
