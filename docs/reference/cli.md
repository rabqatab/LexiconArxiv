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
uv run python -m src.cli.core_collect enrich-citations --parallel 10
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

Collect papers from DBLP.

```bash
# Single venue
uv run python -m src.cli.core_collect collect-dblp --venue icail --since-year 2020

# All DBLP venues
uv run python -m src.cli.core_collect collect-dblp --all
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

### collect-acm

Collect papers from ACM Digital Library.

```bash
# Single venue
uv run python -m src.cli.core_collect collect-acm --venue kdd --since-year 2020

# All venues
uv run python -m src.cli.core_collect collect-acm --all

# Without abstracts (faster)
uv run python -m src.cli.core_collect collect-acm --venue www --no-abstracts
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

Collect from all sources in optimal order.

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

### enrich-citations

Fetch citation data from OpenAlex for papers with DOIs.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-citations --dry-run

# Sequential
uv run python -m src.cli.core_collect enrich-citations

# Parallel (recommended)
uv run python -m src.cli.core_collect enrich-citations --parallel 10

# With limit
uv run python -m src.cli.core_collect enrich-citations --limit 1000
```

### enrich-citations-by-title

Enrich papers without DOIs using title search.

```bash
uv run python -m src.cli.core_collect enrich-citations-by-title --parallel 5
```

### enrich-abstracts

Fetch missing abstracts from OpenAlex.

```bash
# Preview
uv run python -m src.cli.core_collect enrich-abstracts --dry-run

# Run
uv run python -m src.cli.core_collect enrich-abstracts --parallel 10
```

### enrich-s2

Enrich using Semantic Scholar (fallback).

```bash
# By DOI
uv run python -m src.cli.core_collect enrich-s2 --parallel 3

# By title (for papers without DOIs)
uv run python -m src.cli.core_collect enrich-s2 --by-title

# Target specific venues
uv run python -m src.cli.core_collect enrich-s2 --by-title -v "NeurIPS 2024 poster"
```

### enrich-crossref

Enrich papers with references from CrossRef (excellent for ACM/Springer papers).

```bash
# Preview
uv run python -m src.cli.core_collect enrich-crossref --dry-run

# Enrich all papers with DOIs
uv run python -m src.cli.core_collect enrich-crossref

# Limit papers
uv run python -m src.cli.core_collect enrich-crossref --limit 500

# Adjust concurrency (default: 5)
uv run python -m src.cli.core_collect enrich-crossref --parallel 20
```

**Note:** CrossRef has 97% success rate for ACM papers where Semantic Scholar fails. For polite pool access, set `CROSSREF_EMAIL` env var.

### enrich-stubs

Enrich stub papers (external references) with metadata.

```bash
# Enrich top 100 most-cited stubs
uv run python -m src.cli.core_collect enrich-stubs

# Enrich DOI stubs only
uv run python -m src.cli.core_collect enrich-stubs --limit 1000 --type doi

# Only highly-cited stubs (5+ citations)
uv run python -m src.cli.core_collect enrich-stubs --min-citations 5

# Preview
uv run python -m src.cli.core_collect enrich-stubs --dry-run
```

**Options:**
| Option | Description |
|--------|-------------|
| `--type [doi\|arxiv\|openalex]` | Filter by identifier type |
| `--min-citations N` | Only stubs cited N+ times |
| `-n, --limit N` | Max stubs to enrich |
| `-p, --parallel N` | Concurrent API requests |

### extract-pdf-refs

Extract references from PDFs using GROBID.

```bash
# Start GROBID first
docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

# Preview
uv run python -m src.cli.core_collect extract-pdf-refs --dry-run

# Run
uv run python -m src.cli.core_collect extract-pdf-refs --parallel 2
```

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

Extract keywords using a multi-phase pipeline: regex, KeyBERT, LLM extraction (Gemini/Ollama), and LLM judge.

```bash
# Default extraction (regex + KeyBERT)
uv run python -m src.cli.core_collect extract-keywords

# Preview without saving
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Regex only (faster, no model loading)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Better embedding model for KeyBERT
uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

# Full pipeline with Gemini LLM + judge
uv run python -m src.cli.core_collect extract-keywords --llm --judge

# Full pipeline with local Ollama
uv run python -m src.cli.core_collect extract-keywords --llm --judge --llm-backend ollama

# Regex + judge only (validate regex output)
uv run python -m src.cli.core_collect extract-keywords --no-keybert --judge

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
| `--no-keybert` | Skip KeyBERT, use regex only |
| `--force` | Re-extract for papers with existing keywords |
| `--embedding-model` | Sentence-transformers model for KeyBERT (default: `all-MiniLM-L6-v2`) |
| `--llm` | Enable LLM keyword extraction |
| `--llm-backend` | LLM backend: `gemini` (default) or `ollama` |
| `--judge` | Enable LLM judge validation |
| `--judge-backend` | Judge backend: `gemini` or `ollama` (default: same as `--llm-backend`) |
| `--ollama-model` | Ollama model name (default: `llama3.1:8b`) |
| `--gemini-model` | Gemini model name (default: `gemini-2.0-flash`) |

**Behavior:**
- Default: Skips papers that already have keywords
- With `--force`: Re-processes all papers, replacing existing keywords
- With `--llm` or `--judge`: Uses async execution with the full pipeline

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

### list-acm-venues

List ACM Digital Library venues.

```bash
uv run python -m src.cli.core_collect list-acm-venues
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

### clear-enrichment-checkpoint

Clear enrichment checkpoint.

```bash
# Citation enrichment
uv run python -m src.cli.core_collect clear-enrichment-checkpoint

# Abstract enrichment
uv run python -m src.cli.core_collect clear-enrichment-checkpoint --type abstracts
```

### clear-s2-checkpoint

Clear Semantic Scholar enrichment checkpoint.

```bash
uv run python -m src.cli.core_collect clear-s2-checkpoint
```

### clear-crossref-checkpoint

Clear CrossRef enrichment checkpoint.

```bash
uv run python -m src.cli.core_collect clear-crossref-checkpoint
```

### clear-pdf-checkpoint

Clear PDF extraction checkpoint.

```bash
uv run python -m src.cli.core_collect clear-pdf-checkpoint
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
| `OPENALEX_EMAIL` | Email for OpenAlex polite pool (10 req/sec) | Yes |
| `QDRANT_URL` | Qdrant server URL | Yes |
| `QDRANT_API_KEY` | Qdrant API key (for cloud) | No |
| `S2_API_KEY` | Semantic Scholar API key | No |
| `GEMINI_API_KEY` | Gemini API key (for LLM keyword extraction) | No |
| `GOOGLE_API_KEY` | Alternative to `GEMINI_API_KEY` | No |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) | No |

---

## See Also

- [Quick Start Guide](../guides/quickstart.md)
- [Crawling Guide](../guides/crawling.md)
- [Troubleshooting](../guides/troubleshooting.md)
