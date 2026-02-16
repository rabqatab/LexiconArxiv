# LexiconArxiv Scripts

Shell scripts for running the 5-stage data pipeline.

## Quick Start

```bash
# Run full pipeline (collection → dedup → enrichment → resolution → graph)
./scripts/run_full_pipeline.sh --since-year 2020

# Or run individual stages
./scripts/crawler/run_full_collection.sh --since-year 2020
./scripts/maintenance/run_deduplication.sh --apply
./scripts/enrichment/run_enrichment.sh
./scripts/resolution/run_resolution.sh
./scripts/graph/build_cited_by.sh
```

---

## Directory Structure

```
scripts/
├── run_full_pipeline.sh              # Orchestrator: 5-stage pipeline
│
├── crawler/                          # Stage 1: Collection
│   ├── run_full_collection.sh        # Orchestrator: all sources
│   ├── collect_openalex.sh           # Step 1.1: OpenAlex (ML/AI venues)
│   ├── collect_acl.sh                # Step 1.2: ACL Anthology (NLP)
│   ├── collect_dblp.sh               # Step 1.3: DBLP (IR/Legal)
│   ├── collect_openreview.sh         # Step 1.4: OpenReview (ICLR, NeurIPS, ICML)
│   ├── collect_acm.sh                # Step 1.5: ACM Digital Library
│   ├── collect_aaai.sh               # Step 1.6: AAAI OJS
│   ├── run_incremental.sh            # Incremental (current year)
│   ├── check_status.sh               # Status check
│   ├── count_papers.sh               # Estimate papers
│   └── setup_crontab.sh              # Crontab helper
│
├── maintenance/                      # Stage 2: Deduplication
│   └── run_deduplication.sh
│
├── enrichment/                       # Stage 3: Enrichment
│   ├── run_enrichment.sh             # Orchestrator: all enrichment
│   ├── enrich_openalex.sh            # Step 3.1: DOI-based via OpenAlex
│   ├── enrich_crossref.sh            # Step 3.2: CrossRef citations
│   ├── enrich_by_title.sh            # Step 3.3: Title-based lookup
│   ├── enrich_abstracts.sh           # Step 3.4: Abstract enrichment
│   ├── enrich_pdf.sh                 # Step 3.5: PDF/GROBID extraction
│   ├── resolve_title_refs.sh         # Step 3.6: Resolve TITLE:xxx refs via OpenAlex
│   └── enrich_stubs.sh               # Step 3.7: Stub paper metadata
│
├── resolution/                       # Stage 4: Resolution
│   ├── run_resolution.sh             # Orchestrator: all resolution
│   ├── resolve_normalize.sh          # Step 4.1: Fix identifier formats
│   ├── resolve_arxiv.sh              # Step 4.2: arXiv to DOI
│   └── resolve_internal.sh           # Step 4.3: Internal ID resolution
│
└── graph/                            # Stage 5: Graph
    ├── run_graph_pipeline.sh         # Orchestrator: full graph pipeline
    ├── build_cited_by.sh             # Step 5.1: Build cited_by links
    ├── analyze_graph.sh              # Step 5.2: PageRank, communities
    └── export_graph.sh               # Step 5.3: Export to files
```

---

## Full Pipeline

Runs all 5 stages in sequence (payload-only, no vectors required):

| Stage | Name | Description |
|-------|------|-------------|
| 1 | Collection | Collect papers from 6 sources |
| 2 | Deduplication | Remove duplicate papers |
| 3 | Enrichment | Enrich citations and abstracts |
| 4 | Resolution | Resolve references to internal IDs |
| 5 | Graph | Build citation graph (cited_by) |

> **Note**: These stages use **payload-only storage** (points upserted with `vector={}`). Vectors can be added later using Qdrant's named vectors feature. See [Data Model](../docs/architecture/data_model.md#5-qdrant-collection-schema) for details.

```bash
./scripts/run_full_pipeline.sh [OPTIONS]

Options:
  --since-year YEAR     Start year (default: 2020)
  --include-workshops   Include ACL workshop papers
  --skip-collection     Skip Stage 1
  --skip-dedup          Skip Stage 2
  --skip-enrichment     Skip Stage 3
  --skip-resolution     Skip Stage 4
  --skip-graph          Skip Stage 5
  --parallel N          Concurrent requests (default: 10)
  --log FILE            Save output to log file (also prints to terminal)
```

**Example**: Run with logging:
```bash
./scripts/run_full_pipeline.sh --since-year 2017 --log logs/pipeline.log
```

**Example**: Run only post-processing (skip collection):
```bash
./scripts/run_full_pipeline.sh --skip-collection
```

---

## Stage 1: Collection

Collect papers from 6 sources.

### Orchestrator

```bash
./scripts/crawler/run_full_collection.sh [OPTIONS]

Options:
  --since-year YEAR    Start year (default: 2020)
  --include-workshops  Include ACL workshop papers
  --skip-openalex      Skip Step 1.1: OpenAlex
  --skip-acl           Skip Step 1.2: ACL Anthology
  --skip-dblp          Skip Step 1.3: DBLP
  --skip-openreview    Skip Step 1.4: OpenReview
  --skip-acm           Skip Step 1.5: ACM
  --skip-aaai          Skip Step 1.6: AAAI
```

### Individual Steps

| Script | Source | Venues |
|--------|--------|--------|
| `collect_openalex.sh` | OpenAlex | ML/AI conferences (ICML, NeurIPS, ICLR, etc.) |
| `collect_acl.sh` | ACL Anthology | NLP conferences (ACL, EMNLP, NAACL, etc.) |
| `collect_dblp.sh` | DBLP | IR/Legal venues (SIGIR, ECIR, JURIX, etc.) |
| `collect_openreview.sh` | OpenReview | ICLR, NeurIPS, ICML (accepted papers) |
| `collect_acm.sh` | ACM DL | ACM conferences |
| `collect_aaai.sh` | AAAI OJS | AAAI proceedings |

**Example**: Collect only ACL papers since 2023:
```bash
./scripts/crawler/collect_acl.sh --since-year 2023
```

### Utilities

```bash
# Check status and venue listings
./scripts/crawler/check_status.sh

# Estimate paper count
./scripts/crawler/count_papers.sh --since-year 2020

# Incremental collection (current year only)
./scripts/crawler/run_incremental.sh

# Setup cron job (weekly)
./scripts/crawler/setup_crontab.sh --install
```

---

## Stage 2: Deduplication

Remove duplicate papers based on DOI/title matching.

```bash
./scripts/maintenance/run_deduplication.sh [OPTIONS]

Options:
  --dry-run    Preview duplicates without removing (default)
  --apply      Actually remove duplicates
```

---

## Stage 3: Enrichment

Enrich papers with citations and abstracts from external APIs.

### Orchestrator

```bash
./scripts/enrichment/run_enrichment.sh [OPTIONS]

Options:
  --parallel N       Concurrent requests (default: 10)
  --batch-size N     Batch size for updates (default: 50)
  --skip-openalex    Skip Step 3.1: OpenAlex DOI
  --skip-crossref    Skip Step 3.2: CrossRef
  --skip-title       Skip Step 3.3: Title lookup
  --skip-abstracts   Skip Step 3.4: Abstracts
  --skip-pdf         Skip Step 3.5: PDF/GROBID extraction
  --skip-resolve-titles  Skip Step 3.6: TITLE:xxx resolution
  --enrich-stubs     Include Step 3.7: Stub enrichment (expensive)
  --citations-only   Only enrich citations (skip abstracts)
  --abstracts-only   Only enrich abstracts
```

### Individual Steps

| Script | Step | Description |
|--------|------|-------------|
| `enrich_openalex.sh` | 3.1 | Enrich papers WITH DOIs via OpenAlex |
| `enrich_crossref.sh` | 3.2 | Additional citations from CrossRef |
| `enrich_by_title.sh` | 3.3 | Enrich papers WITHOUT DOIs via title search |
| `enrich_abstracts.sh` | 3.4 | Fill missing abstracts via OpenAlex |
| `enrich_pdf.sh` | 3.5 | Extract refs from PDFs via GROBID (fallback) |
| `resolve_title_refs.sh` | 3.6 | Resolve TITLE:xxx refs to DOI/OpenAlex IDs |
| `enrich_stubs.sh` | 3.7 | Fetch metadata for stub papers (optional) |

**Example**: Only enrich abstracts:
```bash
./scripts/enrichment/run_enrichment.sh --abstracts-only
```

**Note**: Step 3.7 (stubs) is expensive (~187K papers) and not included by default.

---

## Stage 4: Resolution

Build citation graph by resolving references to internal paper IDs.

### Orchestrator

```bash
./scripts/resolution/run_resolution.sh [OPTIONS]

Options:
  --dry-run        Preview changes without applying
  --limit N        Limit papers to process (0 = unlimited)
  --skip-normalize Skip Step 4.1: Normalize
  --skip-arxiv     Skip Step 4.2: arXiv resolution
  --skip-internal  Skip Step 4.3: Internal resolution
```

### Individual Steps

| Script | Step | Description |
|--------|------|-------------|
| `resolve_normalize.sh` | 4.1 | Fix identifier formats (e.g., `arXiv:arXiv:` → `arXiv:`) |
| `resolve_arxiv.sh` | 4.2 | Resolve arXiv IDs to DOIs via OpenAlex |
| `resolve_internal.sh` | 4.3 | Resolve all refs to internal Qdrant point IDs |

**Example**: Only run internal resolution:
```bash
./scripts/resolution/resolve_internal.sh
```

---

## Stage 5: Graph

Build and analyze the citation graph.

### Build cited_by links

```bash
./scripts/graph/build_cited_by.sh
```

Creates reverse citation links (who cites this paper).

### Analyze graph

```bash
./scripts/graph/analyze_graph.sh [OPTIONS]

Options:
  --metrics        Compute PageRank and HITS (default)
  --communities    Detect communities
  --output FILE    Output file for results
```

### Export graph

```bash
./scripts/graph/export_graph.sh [OPTIONS]

Options:
  --format FORMAT  Output format: csv, json, graphml
  --output DIR     Output directory
```

---

## Environment Variables

Set these in `.env` or export before running:

```bash
export OPENALEX_API_KEYS=key1,key2,key3        # Comma-separated for round-robin rotation
export OPENALEX_EMAIL=your-email@example.com   # Fallback polite pool when all keys exhausted
export QDRANT_URL=http://localhost:6333
export QDRANT_COLLECTION=lexicon_arxiv
```

---

## Examples

### Full pipeline from 2020

```bash
./scripts/run_full_pipeline.sh --since-year 2020
```

### Collect specific sources only

```bash
# Only OpenReview and ACL
./scripts/crawler/run_full_collection.sh \
  --skip-openalex --skip-dblp --skip-acm --skip-aaai
```

### Enrich stubs separately

```bash
# Stubs are expensive, run separately
./scripts/enrichment/enrich_stubs.sh --parallel 5 --limit 1000
```

### Post-processing only

```bash
# Skip collection, run enrichment → resolution → graph
./scripts/run_full_pipeline.sh --skip-collection --skip-dedup
```
