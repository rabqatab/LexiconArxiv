# LexiconArxiv

AI Research Insights Engine - Hybrid semantic search, on-demand retrieval, trends analytics, and MCP integration for top-tier AI/ML/NLP research papers.

## Features

- **Hybrid Search**: Dense vector (Qwen3-Embedding-8B) + server-side BM25 via Qdrant Reciprocal Rank Fusion
- **Search Web UI**: Interactive search interface at `/search` with faceted filtering, venue dropdown, landing page with corpus stats and trending keywords
- **Keyword Autocomplete**: `GET /api/search/suggest?q=prefix` for real-time keyword suggestions
- **Data Health Dashboard**: Monitoring dashboard at `/dashboard` with pipeline alerting, data validation warnings, and 5-min cached stats
- **MCP Server**: AI agent integration via Model Context Protocol (`search_papers`, `get_paper`, `get_citations`, `get_corpus_stats`, `expand_search` tools)
- **On-demand Retrieval**: User-triggered arXiv + OpenAlex expansion with core/connected/external labeling
- **Trends & Analytics**: Notable paper scoring, keyword trends, rising keywords, UMAP+HDBSCAN topic clustering, and 2D topic map
- **Embedding Pipeline**: Qwen3-Embedding-8B embeddings (1024d via Matryoshka Representation Learning), server-side BM25 index
- **Multi-source Collection**: Collect papers from 6+ academic sources
- **27+ Main Venues**: Tier 0/1/2 conferences and journals
- **90+ Workshops**: ACL-affiliated workshop papers
- **Cross-source Deduplication**: Automatic duplicate detection
- **Checkpoint Resume**: Resumable collection with progress tracking
- **Qdrant Integration**: Payload-only storage with optional named vectors
- **Keyword Extraction**: Regex acronyms + KeyBERT semantic keywords for BM25 search
- **Abstract Labeling**: LLM-based sentence classification into 7 rhetorical roles (task, domain, background, approach, method, result, contribution)
- **Citation Graph**: Reference resolution and GraphRAG support
- **Semantic Similarity Graph**: Precomputed typed similarity edges (same_method, same_task, same_result, method_transfer, overall) using section-level vectors
- **Graph Visualization API**: REST API + D3.js UI for interactive citation graph exploration
- **Stub Papers**: Store external references with automatic deduplication for complete citation graph
- **Snapshot Bootstrap (4 phases)**: Quarterly enrichment from local OpenAlex `works` snapshot — P1 metadata fill, P2 stub→real promotion, P3 hybrid gap discovery + injection, P4 external_cited_by extension
- **Live Mode (daily delta)**: API-driven `process_one(work)` chain over yesterday's OpenAlex updates — same phase logic as the bootstrap, dormant Dagster schedule activated post-bootstrap
- **Dagster Orchestration**: 5 snapshot assets (4 bootstrap + 1 live) + 3 schedules (all STOPPED by default until operator enables)

## Quick Start

### Prerequisites

```bash
# Python 3.11+
python --version

# Start Qdrant (vector database)
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant

# Start GROBID (PDF extraction) - optional
# x86_64:
docker run -d --rm --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0
# ARM64 (Apple Silicon): see docker/grobid-arm64/
```

### Installation

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
# Edit .env with your OPENALEX_EMAIL

# Initialize storage
uv run python -m src.cli.core_collect init-storage
```

### Collection

```bash
# Collect from all sources (recommended)
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# Include workshop papers
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Collect specific source
uv run python -m src.cli.core_collect collect-acl --all --include-workshops
uv run python -m src.cli.core_collect collect-openreview --all
uv run python -m src.cli.core_collect collect-dblp --all --acm-only

# Check status
uv run python -m src.cli.core_collect status
```

### Embedding & Migration

```bash
# Migrate collection to add vector config (creates lexicon_arxiv_v3 — current production)
uv run python -m src.cli.core_collect migrate-collection

# Update .env: QDRANT_COLLECTION=lexicon_arxiv_v3

# Run embedding pipeline (Qwen3-Embedding-8B, 1024d via Ollama)
uv run python -m src.cli.core_collect embed-papers              # standard backlog drain
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue  # drain P2/P3 outputs first
```

### Snapshot Enrichment (quarterly bootstrap + daily live mode)

```bash
# One-time prerequisite: download the OpenAlex `works` snapshot to local SSD (~600GB compressed)
# See docs/runbooks/snapshot-bootstrap.md for full Day 0..11+ procedure.

# Phase dry-runs (idempotent — safe to repeat)
uv run python -m src.cli.core_collect enrich-corpus-fields --dry-run --limit-files 5
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot --dry-run --limit-files 5
uv run python -m src.cli.core_collect discover-corpus-gaps --dry-run --limit-files 5
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot --dry-run --limit-files 5

# Full bootstrap runs (sequence with embedding drains between phases)
uv run python -m src.cli.core_collect enrich-corpus-fields --resume          # P1: ~6-8h
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot --resume   # P2: ~6h + drain
uv run python -m src.cli.core_collect discover-corpus-gaps --resume          # P3: ~4-8h + drain
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot --resume # P4: ~2-3h

# Operational tools
uv run python -m src.cli.core_collect snapshot-status                        # per-phase checkpoint progress
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm    # destructive reset (preserves quarantine.jsonl)
uv run python -m src.cli.core_collect snapshot-replay-failed --phase p2      # list items needing operator review

# Live mode (daily — manually trigger, or enable daily_snapshot_live_schedule in Dagster)
uv run python -m src.cli.core_collect snapshot-live-delta --days-back 1
```

Pipeline references: [P1 metadata fill](docs/pipelines/enrichment.md) · [P2 stub promotion](docs/pipelines/stub-promotion.md) · [P3 gap discovery](docs/pipelines/corpus-gap-discovery.md) · [P4 citation graph](docs/pipelines/citation_graph.md) · [Live mode](docs/pipelines/snapshot-live-mode.md) · [Field mapping](docs/reference/snapshot-fields.md) · [Bootstrap runbook](docs/runbooks/snapshot-bootstrap.md) · [Rollback runbook](docs/runbooks/snapshot-rollback.md)

### API & Search

```bash
# Start the API server
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Search UI
open http://localhost:8000/search

# Trends dashboard
open http://localhost:8000/trends

# Data health dashboard
open http://localhost:8000/dashboard

# Graph visualization
open http://localhost:8000

# API documentation (Swagger UI)
open http://localhost:8000/docs
```

**Search & Retrieval Endpoints**:
- `POST /api/search` - Hybrid search (dense + BM25 fusion) with venue/year/tier filters
- `GET /api/search/suggest?q=prefix` - Keyword autocomplete suggestions
- `POST /api/search/expand` - On-demand expansion via arXiv + OpenAlex
- `GET /api/paper/{paper_id}` - Full paper detail (includes similar papers by section type)
- `GET /api/stats` - Corpus statistics
- `GET /api/dashboard` - Data health monitoring (5-min TTL cache, `?refresh=true` to force)
- `GET /api/corpus-gaps` - Most-cited papers NOT in the corpus + most-referenced uncollected venues (5-min cache)

**Trends & Analytics Endpoints**:
- `GET /api/trends/notable` - Top papers ranked by notable score
- `GET /api/trends/keywords` - Keyword frequency time-series
- `GET /api/trends/rising` - Fastest-growing keywords
- `GET /api/trends/topics` - UMAP+HDBSCAN topic clusters
- `GET /api/trends/map` - 2D topic map coordinates

**Similarity Endpoints**:
- `GET /api/paper/{id}/similar` - Precomputed similar papers by section type

**Graph Endpoints**:
- `GET /graph/health` - Health check
- `GET /graph/stats` - Graph statistics
- `GET /graph/paper/{paper_id}` - Paper details
- `GET /graph/subgraph/{paper_id}?hops=1&direction=both` - Citation subgraph (D3.js format)

**Visualization Features**:
- Shared navigation bar across all pages (Search, Trends, Graph, Dashboard)
- Page titles and favicons on all pages
- Interactive force-directed citation graph with D3.js
- Color-coded edges (cyan=citing, orange=cited, gray=other)
- Click nodes to explore neighborhoods
- Adjustable hops (1-3) and direction

### MCP Server (AI Agent Integration)

```bash
# Start the MCP server (stdio transport)
uv run python -m src.mcp.server
```

Exposes six tools for AI agents via the Model Context Protocol:
- `search_papers` - Hybrid search with venue/year/tier filters
- `get_paper` - Lookup by UUID, DOI, or arXiv ID
- `get_citations` - Citation relationships (refs, cited_by, both)
- `get_similar_papers` - Find semantically similar papers by section type
- `get_corpus_stats` - Corpus summary statistics
- `expand_search` - On-demand expansion via arXiv + OpenAlex

## Data Sources

| Source | Venues | Papers (2020+) | Status |
|--------|--------|----------------|--------|
| OpenAlex | ML/AI/DM conferences | ~40,000 | Active |
| ACL Anthology | NLP venues + workshops | ~30,000 | Active |
| OpenReview | ICLR, NeurIPS, ICML | ~15,000 | Active |
| ACM DL | KDD, SIGIR, WWW | ~10,000 | Active |
| DBLP | IR/Legal venues | ~5,000 | Active |
| AAAI OJS | AAAI (2020-2023) | ~8,000 | Active |

## Venue Tiers

### Tier 0 (Top venues)
- **ML**: NeurIPS, ICML, ICLR, JMLR
- **AI**: AAAI, IJCAI
- **NLP**: ACL, EMNLP
- **IR/DM**: KDD, WWW, SIGIR

### Tier 1 (Strong venues)
- **NLP**: NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC
- **IR/DM**: WSDM, CIKM, ICDM, ECIR, RecSys, TOIS, ESWA

### Tier 2 (Specialized)
- **Legal AI**: AILaw, ICAIL, JURIX
- **Workshops**: BioNLP, SemEval, ArgMining, and 90+ more

## CLI Commands

```bash
# List available venues
uv run python -m src.cli.core_collect list-venues
uv run python -m src.cli.core_collect list-acl-venues
uv run python -m src.cli.core_collect list-openreview-venues

# Collection commands
uv run python -m src.cli.core_collect collect-all-sources [options]
uv run python -m src.cli.core_collect collect-acl [options]
uv run python -m src.cli.core_collect collect-openreview [options]
uv run python -m src.cli.core_collect collect-dblp [options]      # includes ACM venues
uv run python -m src.cli.core_collect collect-aaai [options]

# Maintenance
uv run python -m src.cli.core_collect status
uv run python -m src.cli.core_collect deduplicate --dry-run
uv run python -m src.cli.core_collect clear-checkpoint
uv run python -m src.cli.core_collect reset-title-enriched --dry-run   # Reset title-matched papers
uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v3 --confirm

# Enrichment (add citations/abstracts)
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10    # OpenAlex
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel 5      # CrossRef (ACM/Springer)
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2                         # Semantic Scholar
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10    # Abstracts
uv run python -m src.cli.core_collect enrich-oa-pdf-by-doi-via-unpaywall --parallel 10        # Unpaywall OA PDF URLs

# Resolve TITLE:xxx refs from GROBID (fuzzy match via OpenAlex)
uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --parallel 3

# Code repository enrichment (find GitHub repos for papers)
uv run python -m src.cli.core_collect enrich-10-code-repos --parallel 10             # PWC + HuggingFace
uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --parallel 5    # GROBID PDF extraction
uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --batch-size 50 # GitHub API search

# Retry enrichment for papers still missing data after rate limits
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --retry-incomplete
uv run python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --retry-incomplete
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --retry-incomplete

# Reference Resolution (build citation graph)
uv run python -m src.cli.core_collect ref-stats
uv run python -m src.cli.core_collect resolve-refs
uv run python -m src.cli.core_collect resolve-refs --create-stubs       # Create stub papers

# Citation Graph Analysis
uv run python -m src.cli.core_collect citation-graph-stats
uv run python -m src.cli.core_collect build-citation-graph -o graph.json
uv run python -m src.cli.core_collect analyze-citation-graph --all --top-n 10
uv run python -m src.cli.core_collect get-citing-papers <paper_id>
uv run python -m src.cli.core_collect build-cited-by  # Required for GraphRAG

# Stub Papers (external references)
uv run python -m src.cli.core_collect stub-stats                        # Most-cited external papers
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --limit 1000         # Fetch metadata for stubs
uv run python -m src.cli.core_collect reconcile-stubs --recent-days 7 --dry-run  # Promote stubs shadowed by new real papers (preserve cited_by)

# Keyword Extraction (for BM25 search)
uv run python -m src.cli.core_collect extract-keywords              # Regex + KeyBERT (production)
uv run python -m src.cli.core_collect extract-keywords --no-keybert # Regex only (faster)
uv run python -m src.cli.core_collect extract-keywords --dry-run    # Preview mode
uv run python -m src.cli.core_collect keyword-stats                 # Show statistics

# Abstract Labeling (sentence-level rhetorical classification)
uv run python -m src.cli.core_collect label-abstracts --dry-run --limit 5  # Preview
uv run python -m src.cli.core_collect label-abstracts --limit 100          # Label papers (Ollama)
uv run python -m src.cli.core_collect label-abstracts --force --limit 50   # Re-label

# Snapshot Enrichment (see docs/runbooks/snapshot-bootstrap.md)
uv run python -m src.cli.core_collect enrich-corpus-fields           # P1: metadata fill from OpenAlex snapshot
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot --min-cites-per-year 5  # P2: promote stubs (age-normalized citation gate)
uv run python -m src.cli.core_collect discover-corpus-gaps           # P3: hybrid-classified gap injection
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot  # P4: external_cited_by union
uv run python -m src.cli.core_collect snapshot-live-delta            # daily live-mode API delta
uv run python -m src.cli.core_collect snapshot-status                # operational status
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm  # reset phase checkpoint
uv run python -m src.cli.core_collect snapshot-replay-failed --phase p2    # list failed batches
```

## Documentation

- [Crawling Guide](docs/guides/crawling.md) — Detailed collection guide
- [BM25 Migration](docs/guides/bm25_migration.md) — Enable hybrid search (dense + BM25)
- [Data Collection Design](docs/pipelines/data_collection.md) — Architecture and strategy
- [Keyword Extraction](docs/pipelines/keyword_extraction.md) — LLM-first keyword pipeline
- [Abstract Labeling](docs/pipelines/abstract_labeling.md) — Sentence-level rhetorical classification
- [Snapshot System Spec](docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md) — Quarterly bootstrap + daily live mode architecture
- [Snapshot Bootstrap Runbook](docs/runbooks/snapshot-bootstrap.md) — Day 0..11+ operational procedure
- [Snapshot Rollback Runbook](docs/runbooks/snapshot-rollback.md) — 4 rollback scenarios
- [Graph API Specification](docs/architecture/api.md#8-graph-visualization-api) — Graph Visualization API
- [Full Documentation Index](docs/README.md)

## Project Structure

```
lexiconarxiv/
├── src/
│   ├── api/                     # REST API (FastAPI)
│   │   ├── main.py              # FastAPI app with lifespan
│   │   ├── dependencies.py      # Service container (storage, search, graph)
│   │   ├── routes/
│   │   │   ├── graph.py         # /graph/* citation graph endpoints
│   │   │   ├── search.py        # /api/search, /api/paper, /api/stats
│   │   │   └── trends.py        # /api/trends/* analytics endpoints
│   │   ├── models/              # Pydantic request/response models
│   │   └── static/
│   │       ├── index.html       # D3.js citation graph UI
│   │       ├── search.html      # Search web UI
│   │       └── trends.html      # Trends dashboard
│   ├── mcp/                     # MCP Server (AI agent integration)
│   │   ├── server.py            # Tool definitions + handlers (stdio transport)
│   │   └── formatters.py        # Output formatters for tool results
│   ├── cli/                     # CLI tools
│   │   ├── core_collect.py      # Main CLI entry point
│   │   └── commands/            # CLI command modules
│   ├── orchestration/           # Dagster assets, jobs, schedules
│   │   ├── assets/              # 5 snapshot assets + DQ + ingest/transform
│   │   ├── jobs.py              # core_job + maintenance_job + snapshot_*_job
│   │   ├── schedules.py         # 3 schedules (all STOPPED by default)
│   │   └── definitions.py       # Dagster Definitions registration
│   ├── core/                    # Core modules
│   │   ├── snapshot/            # OpenAlex snapshot bootstrap (Plans 1-5)
│   │   │   ├── phase1_corpus_fields.py      # P1: metadata fill
│   │   │   ├── phase2_stub_resolution.py    # P2: stub→real promotion
│   │   │   ├── phase3_gap_discovery.py      # P3: hybrid gap injection
│   │   │   ├── phase4_cited_by.py           # P4: external_cited_by union
│   │   │   ├── live_worker.py               # daily API delta chain
│   │   │   ├── work_source.py               # iter_snapshot_works + iter_live_works
│   │   │   ├── gap_filter.py                # AI taxonomy + classification
│   │   │   ├── matcher.py / promotion.py    # DOI/arXiv/title matching, stub merge
│   │   │   ├── checkpoint.py / embedding_queue.py / stats.py
│   │   │   └── extractor.py                 # OpenAlex work → payload
│   │   ├── storage/             # Qdrant storage package
│   │   ├── search/              # Search & on-demand retrieval
│   │   │   ├── service.py       # SearchService (hybrid search orchestrator)
│   │   │   ├── on_demand.py     # On-demand arXiv + OpenAlex expansion
│   │   │   ├── arxiv_client.py  # arXiv API client
│   │   │   └── openalex_client.py  # OpenAlex search client
│   │   ├── embedding/           # Embedding pipeline
│   │   │   ├── embedder.py      # Qwen3-Embedding-8B batch embedder
│   │   │   └── migration.py     # Collection migration (payload → vectors)
│   │   ├── analytics/           # Trends & analytics
│   │   │   ├── notable.py       # Notable paper scoring
│   │   │   └── keyword_trends.py  # Keyword trends + rising detection
│   │   ├── checkpoint.py        # Resume support
│   │   ├── config.py            # Venue configurations
│   │   ├── constants.py         # Centralized API URLs and env helpers
│   │   ├── deduplication.py     # Cross-source dedup
│   │   ├── citation_graph/      # Citation graph analysis
│   │   │   ├── builder.py       # CitationGraphBuilder (NetworkX)
│   │   │   ├── reverse_index.py # ReverseCitationIndex
│   │   │   └── exporter.py      # Graph export (CSV, JSON, GraphML)
│   │   ├── crawler/             # Data source crawlers
│   │   │   ├── base.py          # BaseCrawler class
│   │   │   ├── openalex.py
│   │   │   ├── acl_anthology.py
│   │   │   ├── openreview.py
│   │   │   ├── acm_open.py
│   │   │   ├── dblp.py
│   │   │   └── aaai_ojs.py
│   │   ├── enrichment/          # Enrichment pipelines
│   │   │   ├── base.py          # BaseEnricher, OpenAlexMixin, CrossRefMixin
│   │   │   ├── openalex.py      # Citation/abstract via OpenAlex
│   │   │   ├── crossref.py      # CrossRef (ACM/Springer papers)
│   │   │   ├── semantic_scholar.py  # S2 fallback
│   │   │   ├── stub.py          # Stub paper enrichment with dedup
│   │   │   ├── pdf.py           # PDF reference extraction
│   │   │   ├── code_repos.py    # Code repos via PWC/HuggingFace
│   │   │   ├── grobid_code_repos.py  # GitHub URLs from PDFs via GROBID
│   │   │   └── github_search.py # GitHub API code repo search
│   │   ├── resolution/          # Reference resolution
│   │   │   ├── normalizer.py    # ID normalization (DOI, arXiv, OpenAlex)
│   │   │   └── resolver.py      # Citation graph builder
│   │   ├── keyword/             # Keyword extraction
│   │   │   ├── extractor.py     # KeywordExtractor (sync + async pipeline)
│   │   │   ├── patterns.py      # Regex patterns for acronyms
│   │   │   ├── stopwords.py     # Stopword filtering
│   │   │   ├── llm_base.py      # Pydantic models, prompts, ABC base classes
│   │   │   ├── ollama.py        # Ollama REST API extraction + judge
│   │   │   └── judge.py         # KeywordJudge wrapper
│   │   └── labeling/            # Abstract sentence labeling
│   │       ├── labeler.py       # AbstractLabeler orchestrator (pysbd + LLM)
│   │       ├── llm_base.py      # Models, prompts, helpers, ABC
│   │       └── ollama.py        # Ollama REST API labeling (granite4.1:8b)
│   └── models/
│       └── paper.py             # Paper data model
├── scripts/
│   └── embedding/               # Embedding pipeline scripts
│       ├── run_embedding.sh     # Run batch embedding
│       └── migrate_collection.sh  # Migrate Qdrant collection
├── docs/                        # Documentation
├── tests/                       # Test suite
└── data/core/checkpoints/       # Collection state
```

## Recent Updates

### v0.14.0 (Jul 2026) — Backlog sweep: TITLE-stub unblock, stub→core, corpus-gaps, batch-write Wave 1e, Unpaywall

- **TITLE-stub resolution unblocked (matcher data-shape bug).** The 751,936 `identifier_type=title` stubs leave `title` empty and carry the raw GROBID title in `identifier` as `TITLE:<text>`, but `build_stub_index` read only `stub['title']` — so they were **invisible to the snapshot matcher and never resolvable**. Fixed to derive the title from `identifier` (4-word floor drops bare fragments); real-data check: 96.1 % of a 5K sample now index (was 0 %). Full resolution still runs through the local snapshot P2 (online title-search is a per-IP 429 trap) — gated on disk.
- **Stub → core promotion (`reconcile-stubs`).** Incremental collection adds a real paper for a work a prior reference already stubbed, orphaning the stub's `cited_by` (~1.77 % of real papers, ~21 K corpus-wide). New `reconcile_stub_duplicates` + `find_stub_by_identifier` (indexed probes) + incremental Step 8.5 merge the stub's cited_by into the real paper before build-cited-by. Bulk-safe (recent-days scoped).
- **Corpus-gaps dashboard.** `/api/corpus-gaps` + a Data Health Monitor section list the most-cited papers NOT in the corpus (e.g. Bleu, Classifier-Free Diffusion Guidance, MT-Bench) + most-referenced uncollected venues, via server-side `order_by` on `cited_by_count_internal` (317 ms).
- **Batch-write Wave 1e.** Converted 10 per-point `set_payload` loops (keywords, refs, abstracts, graph metrics, code repos, field-fill, …) to a single `batch_update_points` + `wait=False` — **9.3× faster** on a live 500-point bench (567 → 5,253 writes/s). All are fill-only-missing (idempotent) so `wait=False`'s ~5 s crash window is safe; the one in-process read-after-write (resolver normalize→resolve) is protected by re-normalization on read.
- **Unpaywall OA-PDF enricher.** `enrich-oa-pdf-by-doi-via-unpaywall` fills `pdf_url` (+`oa_status`) for DOI-bearing papers with no PDF link; free, no API key. Live-verified.
- **Also:** research-API type exclusion no longer shrinks results below `limit` (over-fetch scaling); venue normalization confirmed already shipped (TEXT index + alias map); stub-dedup audit and zero-title-stub investigation both closed as not-bugs (uuid5 stub IDs + resolver normalization prevent duplicates; empty-title stubs are the gated title-type / fabricated-ID / low-cited classes, not an enrich-8 failure).

### v0.13.9 (Jul 2026) — Enricher-hang root cause + Ollama re-label verdict + labels-reach-search re-embed

- **StubEnricher hang fixed (root cause, not symptom):** every run that actually enriched stubs stalled at 0 % CPU. First hypothesis (20 K-task `asyncio.gather` pileup) was **wrong** — bounded chunking alone didn't fix it. Real cause: `find_stub_by_alternate_identifier` scrolled `alternate_identifiers.{doi,arxiv,openalex}` — all **unindexed** — over 5 M stubs = 60-150 s Qdrant timeout per enriched stub, serialized on the async loop. Indexed the three nested fields → arxiv `--limit 30` went from a >100 s hang (zero output) to **7.2 s** (30 processed, 7 enriched, 16 merged). Same unindexed-filter-at-scale class as Wave 4c, recurring in a different code path.
- **Ollama re-label: verified unnecessary, closed.** The "Issue B" backlog assumed Ollama labels were inferior/partial. Both premises are false: Ollama and vLLM run the **same model** (granite-4.1-8b — the migration was throughput, 750/hr → 30 K/hr), and the "Ollama truncates long abstracts" claim is disproven (long-abstract Ollama-labeled papers carry `result`/`contribution` tail roles 100 % of the time). Scope was 9,670 papers, not the feared ~250 K.
- **Labels-reach-search re-embed:** the actual gap was **section vectors, not labels** — ~51 K labeled papers (mostly vllm 2010+, a recurring post-Phase-4b gap where labeling ran but section-vector re-embedding didn't) had `abstract_structure` but no `section-*` vectors, so their labels never reached multi-vector search. `reembed_labeled_sections.py` now matches vllm OR ollama; the 2010+ re-embed completed (30,591 papers, ~3.9 h, `indexed_vectors` 3.21 M → 3.39 M; section-level search verified). ~19 K method-less papers show as a stable "remaining" count — not a gap: they carry structured-abstract + their other section roles and are searchable, they just have no `method` section to embed (documented in the script).

### v0.13.8 (Jul 2026) — Corpus quality (type gate) + stub scale-up + retrieval pipeline completion

Closed the remaining corpus-quality and retrieval backlog. Measure-first paid off: most of the "advanced retrieval" backlog turned out already shipped, and the stub-enrichment "scheduling gap" was really a 5 M-scroll scale bug.

- **A1(a) — non-paper `type` gate inside the CS keep-set:** Wave 4c removed cross-domain junk by *topic*; this removes the non-paper *types* that stayed on-topic (a `book` whose abstract is a table-of-contents, an `editorial` in a CS journal). Measured 165 K non-article works in the 1.19 M keep-set, demoted **44,287** clear non-paper types (book/paratext/editorial/peer-review/…) to stubs — KEEPING `review` (60.7 K surveys), `book-chapter`, `dissertation`, `report`, `dataset`, `letter`, and all no-type crawler papers. Durable `topic_gate.is_keep_type` at P2/P3 + `nonpaper_type_share` DQ warn-check (baseline 0 %).
- **A3 — high-value stub selection made scalable:** `get_most_cited_stubs` full-scrolled all **5.0 M** stubs and sorted in Python on every enrich call — the real reason cited-but-absent papers never got enriched. Added an integer index on `cited_by_count_internal` + keyword on `identifier_type` and a server-side `order_by` rewrite: **5 M-scroll → 39 ms**. (Enrichment yield is inherently low — the highest-cited stubs are ~17 % fabricated 6-billion OpenAlex IDs that 404; a StubEnricher async-gather hang at scale is filed as a follow-up.)
- **A4 — similarity graph 67× faster:** the bottleneck was the per-paper `set_payload` write loop, not the (already batched) query. Now one `batch_update_points(wait=False)` per batch + a `--only-missing` incremental mode (453 K embedded → 137 K without edges). **Verified 0.11 s/paper** (was 7.4 s); daily runs touch only new papers.
- **B — retrieval pipeline completed:** the core (RetrievalConfig, fast/quality/comprehensive presets, RAG-Fusion, reranker, MMR, citation-boost, HyDE, pipeline-info) was already shipped. Added the last four: **query decomposition** (split "BERT vs GPT for code" into sub-questions), **neural PRF** (2-pass query-vector refinement — reshapes ranking DiffCSE→SimCSE), **adaptive-weighted RRF** (tilt dense-vs-BM25 candidate share by query shape), and **stub-vectors** — embedded the **10,842** most-cited abstract-bearing stubs and gated them via `searchable_stub` so exactly those cited-but-absent papers surface (WMT22/COMET-22 now findable) while the other ~5 M stubs stay out of the HNSW, preserving Wave 4c's search-speed win. Also fixed a latent HyDE/RAG-Fusion bug: qwen3:8b's thinking mode ate the 10 s budget → empty output; `think:false` makes all LLM query stages reliable.

### v0.13.7 (Jul 2026) — Wave 4c Phase 4/4b: label + re-embed the keep-set; MCP search hardened

Turned the cleaned corpus's labels into actual search quality, and fixed a silent search degradation.

- **Phase 4 — chronological labeling (2020+):** vLLM-labeled the keep-set backlog newest→oldest — 2025-26 (2,109) + 2020-24 (103,297) at ~6 K/hr. Pre-2020 deliberately skipped (recent papers are the search-relevant ones). Enablers: `label-abstracts --year-min/--year-max` (year is indexed → avoids the unindexed `abstract_structure` full-scan timeout) + **stub exclusion** in the labeling filter (was counting ~8 K enriched stubs = wasted GPU).
- **Phase 4b — re-embed for section vectors:** labeling writes `abstract_structure`, but those papers already had a stale `structured-abstract` vector so the normal embed path skipped them → no `section-*` vectors → multi-vector search collapsed. Re-embedded 113,033 papers (`scripts/analytics/reembed_labeled_sections.py`) → `indexed_vectors` 2.3 M → **3.19 M**. Verified: a "method for contrastive learning…" query now section-matches EASE/miCSE/PCL exactly.
- **MCP search fix:** search had silently fallen back to `bm25_only` — the Ollama embed model (`qwen3-embedding:8b`, ~14.6 GB) was idle-evicted (`OLLAMA_KEEP_ALIVE=1h`) and its ~10 s cold-load exceeded the 5 s query-embed + handler timeouts. Now the MCP server **preloads the embed model at startup** and the timeouts were raised to 30 s (`SearchService.query_timeout`, `search_papers`/`research_topic` budgets), so a post-idle reload returns `hybrid` instead of degrading.

Ops note: big in-place write passes (label/re-embed) on the shared root disk keep flirting with the "optimizer can't compact → RED" state; both recurrences this cycle were cleared without data loss (ssd2-scratch compaction once, `docker restart qdrant` to clear a stale optimizer error the second time). Durable fix = a dedicated disk with headroom. Qdrant is GREEN, 6.22 M points.

### v0.13.6 (Jul 2026) — Wave 4c corpus CS-cleanup: ML/NLP-focused, search 2× faster

The corpus audit found only **32.6 %** of the 3.74 M non-stub real papers were AI/NLP-adjacent — the rest were cross-domain works (Medicine, Engineering, Biochemistry, Physics…) pulled in by P2/P3 anchor+concept injection with no topic gate. Fixed in two halves:

- **Durable gate** (`src/core/snapshot/topic_gate.py`): `KEEP_FIELDS = {Computer Science, Mathematics, Decision Sciences, Neuroscience, Psychology}` ∪ subfield `Language and Linguistics`, wired into P3 (`reject_topic`) and P2 (PROMOTE→ENRICH_KEEP_STUB) so the next quarterly bootstrap can't re-pollute. Two warn-only DQ checks (`nontarget_topic_share`, `no_primary_topic_share`), both provenance-scoped so crawler/tier-venue papers are exempt.
- **One-time cleanup**: 2,483,834 non-CS P2/P3 papers **demoted to stubs** (not deleted — chosen after measuring that hard delete reclaims only ~35 GB / 15 %). Demotion strips heavy payload + vectors, keeps identity + `cited_by` edges, and is reversible (re-promote). Non-stub real papers **3.74 M → 1.26 M**.

**Result: MCP search ~2× faster** (p50 433 ms → ~200 ms) — the demoted vectors left the HNSW graph entirely (715 K → 426 K searchable). Crawler-provenance protection keeps ~66 K ICLR/NeurIPS/ACL papers that OpenAlex mis-fields. Full record: [`docs/plans/2026-07-06-corpus-cs-cleanup.md`](docs/plans/2026-07-06-corpus-cs-cleanup.md) §8. (Phase 4/4b labeling + re-embed followed — see v0.13.7 above.)

### v0.13.5 (Jul 2026) — Ponytail cleanup wave: −3,600 lines, −4 deps

Both ponytail audits (2026-06-24 deferred list + 2026-07-07 re-audit) applied in one wave, now that the bootstrap is done and the incremental is stable. Deleted dead code: `src/collectors/` (superseded by `src/core/crawler/`), the never-enabled keyword-LLM extraction/judge path, `external_search` in the resolver, the deprecated `run_snapshot_enrichment` chain (use `enrich-corpus-fields`), `checkpoint_mixin`, the `get_payload` alias, and stale one-off scripts. Consolidated: one shared Qdrant retry helper (`src/core/storage/_retry.py`, Wave 1e-bis), one canonical title normalizer (`Deduplicator.normalize_title`, now accent-insensitive). Dropped deps: `feedparser`, `cachetools`, `python-dateutil`, `auto-mix-prep`. Deliberate skips (facade dismantle, stub-ID scheme, fuzzy flag) recorded with reasons in [`docs/refactoring/2026-06-24-ponytail-audit.md`](docs/refactoring/2026-06-24-ponytail-audit.md) §Application record. Full suite green (419 → 369 tests after dead-path test removal); Dagster definitions validate.

### v0.13.4 (Jul 2026) — True-incremental overhaul + Qdrant payload indices + GROBID fallback

The 2026-07-06→08 campaign took the incremental pipeline from "dies on a different Qdrant timeout every attempt" (runs `830c`, `d582`, `7e38`, `e450`, `c0c7`, `21fe`, `7a34`) to a **~1.5 h end-to-end completion** (`6283`, v8). Two intertwined root causes fell out of the investigation, each now codified as a design rule in [`docs/design/bulk-vs-incremental-audit.md`](docs/design/bulk-vs-incremental-audit.md).

- **Qdrant filter-index gap (Third rule)** — at 6.2 M points, any bulk-scroll filter on an unindexed payload field is a deterministic 60–150 s server-side timeout, and retry can't help. Fixed by adding **9 payload indices** across three batches (`abstract_structure_source`, `injected_from_snapshot`, `snapshot_filled_at`, `year`, `type`, `promoted_from_stub`, `tier`, `graph_indexed` + pre-existing 7). Runbook with create/verify commands: [`docs/runbooks/qdrant-tuning.md`](docs/runbooks/qdrant-tuning.md) §Payload indices. Full field catalog (what each field means, which stage writes it, DQ rules, index status): [`docs/reference/qdrant-payload-catalog.md`](docs/reference/qdrant-payload-catalog.md).
- **True-incremental gap (Fourth rule)** — "incremental" is a property each stage must enforce, not one the script name grants. Steps 5/6/7/10 default-swept their full backlogs (a 33-day gap-fill run became a 3.97 M-paper keyword sweep + 13 h labeling job + 7 h+ Step 7.1 Normalize). `--recent-days` (→ indexed `fetched_at` range) now threads through **every eligible stage**: enrich-6/enrich-4/enrich-2, extract-keywords, label-abstracts, resolve-refs (all 3 resolver sub-steps), embed-papers. `run_incremental_pipeline.sh` derives it from `--days` with a +2 margin.
- **Step 9 index-only filter** — `build-cited-by --incremental` had correct mark-and-skip logic but its `must` clause on unindexed `resolved_references` forced a full scan; rewritten to filter on indexed `graph_indexed` + `is_stub` and check the unindexed field client-side (60 s timeout → 0.04 s/page).
- **GROBID PDF fallback (Steps 4b/4c)** — audit showed ~90 % of recent ACL/DBLP papers still had no `referenced_works` after the S2+CrossRef passes. `enrich-5-refs-by-pdf-via-grobid` + `enrich-7-abstracts-by-pdf-via-grobid` now run in the incremental script, `--recent-days`-scoped, with Docker auto-start/auto-stop of the **`grobid-arm64:latest`** container (upstream `lfoppiano/grobid` is amd64-only and silently fails on the DGX Spark) and graceful `[SKIP]` when Docker is absent.
- **vLLM labeling truncation contract** — real corpus abstracts measured p50 8.1 K / p90 25.6 K chars (structured medical abstracts, and P3-injected books/peer-review threads with body text in the `abstract` field). `label_abstract` now caps the LLM slice at 25 sentences; full text still feeds the embedding vectors. Plus deterministic short-circuits for HTTP 400 (context overflow) and `finish_reason=length`.
- **Corpus quality findings queued** — sampling revealed only **32.6 % of the 3.56 M non-stub papers are AI/NLP-adjacent** by `primary_topic.field` (Medicine 487 K, Engineering 415 K, Biochemistry 424 K, …), plus non-article types (books, peer-review threads, editorials) leaked by P3. Cleanup plan (Wave 4c, ~2.4 M deletions + durable P2/P3 topic gate): [`docs/plans/2026-07-06-corpus-cs-cleanup.md`](docs/plans/2026-07-06-corpus-cs-cleanup.md). Trigger: post-catchup-stable.
- **Batched abstract-structure writes** — `batch_update_abstract_structure` now uses `batch_update_points` (1 HTTP call per 500 updates, `wait=False`) instead of 500 sequential `set_payload` calls.
- **`retrofit-tier-from-source-id` CLI + `openalex_source_id` extraction** — P2/P3 papers never got `tier` (crawlers set it venue-first at write time); P1 now extracts the venue Source ID from the snapshot so tier can be joined retroactively against the venue config.

### v0.13.3 (Jul 2026) — Labeling gap + vLLM migration (Path B) + pipeline audit

The 2026-07-04 verification revealed that **P2-promoted (~940K) and P3-injected (~2M+) papers all lack `abstract_structure`** — no snapshot bootstrap phase runs abstract labeling, and nobody had noticed. Downstream: default MCP search's multi-vector prefetch collapses to a single dense signal on 90% of the post-bootstrap corpus. We fixed both the immediate problem and the class-of-problem that hid it.

- **Bulk-vs-incremental audit** ([`docs/design/bulk-vs-incremental-audit.md`](docs/design/bulk-vs-incremental-audit.md)) systematically mapped every incremental pipeline step against the bulk chain and surfaced **7 hidden gaps**: labeling (known), embed drain (known), reference resolution (new), similarity graph (new), citation graph analysis (new), keyword extraction (new), topic clustering (new).
- **Post-bootstrap catchup runbook** ([`docs/runbooks/post-bootstrap-catchup.md`](docs/runbooks/post-bootstrap-catchup.md)) — 7-step sequence with exact sparkq commands, dependencies, verify+rollback for each gap. Bootstrap is no longer "done at P4"; this runbook is the required follow-up.
- **Ollama → vLLM (Path B)**: Ollama chat is retired from every pipeline stage. Measurements — Ollama labeling caps at ~750 papers/hr (serial-chat GPU pipeline, zero benefit from concurrency); Ollama embedding stays at ~88K/hr (batched internally). vLLM handles all chat (labeling); Ollama continues to serve embedding (bulk + incremental + search-time query embed) and search-time HyDE. Vector-space integrity for search recall was the deciding factor over any pipeline-side speedup.
- **vLLM labeling backend** (`src/core/labeling/vllm.py`) — mirror of `OllamaAbstractLabeler` over vLLM's OpenAI-compatible API with `guided_json` enforcement of the same `SentenceLabels` schema. CLI: `label-abstracts --backend ollama|vllm`. Sparkq launcher: [`scripts/labeling/serve_vllm.sh`](scripts/labeling/serve_vllm.sh). Model: `ibm-granite/granite-4.1-8b` (same family as Ollama default).
- **Quality gate** ([`scripts/labeling/eval_labeling_quality.py`](scripts/labeling/eval_labeling_quality.py)) — 60-paper baseline-vs-candidate agreement eval (Jaccard mean + per-role micro-F1). Pass condition: ≥0.85 agreement AND ≥55/60 schema-valid on both backends. JSON to stdout, graceful failure never surfaces as a traceback.
- **vLLM ops runbook** ([`docs/runbooks/vllm-labeling.md`](docs/runbooks/vllm-labeling.md)) — boot / healthcheck / restart / troubleshoot / shutdown via sparkq. Rule of thumb: if Ollama at 750/hr would take under an hour, keep Ollama; everything else → vLLM.
- **DQ warn-check** for the labeling gap — `abstract_labeling_gap` in `src/core/pipeline/dq.py`, wired into the `label_abstracts` Dagster asset and the `data-quality` CLI. WARNs when >1000 real papers have `abstract` but no `abstract_structure`. Metadata carries the runbook pointer so ops knows the fix without paging code.
- **Priority-tier drain** — `embed-papers --priority-tier N` for two-phase embed (tier 0/1 first, then everything else) so search becomes useful on the hot subset within hours instead of days. 10 L3 crash-safety tests lock in the invariants of the 2026-06-30 663K-loss incident under the new priority filter path.
- **Embed drain strategy runbook** ([`docs/runbooks/embed-drain-strategy.md`](docs/runbooks/embed-drain-strategy.md)) — 4-lever plan (parallelism, benchmark, P4-in-parallel, tier priority) + explicit "do NOT" list. Benchmark helper: [`scripts/embedding/benchmark_drain.sh`](scripts/embedding/benchmark_drain.sh).
- **[gpu] extra** in `pyproject.toml` — installs vLLM + xgrammar for the labeling server; base install unchanged for non-GPU hosts.
- **Docs sweep**: `docs/pipelines/abstract_labeling.md`, `docs/pipelines/keyword_extraction.md`, `docs/guides/crawling.md` updated for Path B (vLLM backend documented, `--llm --judge` explicitly deprecated at bulk scale, historical Gemini refs cleared). `.gitignore` extended to silence local scratch (`poc_*.py`, `audit_*.py`, `run_complete_chain_*.sh`).
- **Overhaul plan** ([`docs/refactoring/2026-07-04-code-overhaul-plan.md`](docs/refactoring/2026-07-04-code-overhaul-plan.md)) — waves of cleanup queued for the post-bootstrap stability window: DQ registry, CLI reorg, storage layer consolidation, vector schema versioning, dep prune, deprecation removals. Executes on the same trigger as the ponytail audit (corpus stable ≥ 1 week AND bootstrap complete).
- **Phase 1 gate verified (2026-07-04)** — vLLM served from `nvcr.io/nvidia/vllm:25.11-py3` (aarch64 GB10). Quality: 60/60 schema-valid on both baselines, per-role micro-F1 0.83–0.93, overall Jaccard 0.834 accepted after multi-label-lens review. Throughput scaling: 2.4K/hr @ -p 4 → 8.3K @ -p 16 → 22K @ -p 64 → **35.6K/hr @ -p 128**. Projected wall-clock for the 3.74M-paper labeling gap: **~4.4 days** on vLLM vs ~208 days on Ollama (~47× speedup).
- **Qdrant client timeout raised** (`60s → 300s`, `QDRANT_TIMEOUT` env override, commit `c342171`) after the CLI bench hit read-timeouts on the `count_papers_for_abstract_labeling` filter and sequential `set_payload` writes at catchup scale.
- **NGC vLLM container required on DGX Spark** (commit `5495eda`) — the PyPI vLLM wheels are x86_64/CUDA and fail to import on aarch64 (Grace-Blackwell) with `libtorch_cuda.so cannot open shared object file`. `serve_vllm.sh` now wraps `docker run nvcr.io/nvidia/vllm:25.11-py3`. The `[gpu]` pyproject extra is preserved for x86_64 dev-laptop use only.
- **`response_format` not `extra_body`** (commit `24b7439`) — `VLLMAbstractLabeler` originally passed the JSON schema via OpenAI-Python-SDK's `extra_body` convention; that field is client-side-unpacked, so posting raw JSON via httpx sends the wrapper over the wire and vLLM drops it. Fix: top-level `response_format: {type: json_schema, json_schema: {name, schema}}`.
- **Full-catchup runtime discoveries (2026-07-04 same day, commits `c61a652` + `9636d66`):**
  - **Client-side retry on bulk writes.** Step 1 (labeling job b2ab) died in 573 s on a single `set_payload` timeout inside `batch_update_abstract_structure` — the whole 500-paper batch's vLLM work was thrown away because the client loop had zero retry. New `_retry_qdrant_call` helper wraps each write in exponential backoff (1→2→4→8→16 s, capped 30 s) on transient `ResponseHandlingException` / 5xx / 429. Permanent 4xx propagates. Applied at `batch_update_abstract_structure`; the [code overhaul plan](docs/refactoring/2026-07-04-code-overhaul-plan.md) Wave 1 item **1e** queues the same treatment for `batch_update_code_repos`, `batch_extend_external_cited_by`, `batch_inject_papers`.
  - **Qdrant background-thread caps for mixed read/write load.** Default `hnsw_config.max_indexing_threads=0` and `optimizers_config.max_optimization_threads=null` are both unlimited — background HNSW indexing + segment-merge starves user search of CPU. Under the labeling job, multi-vector `SearchService.search` hit Qdrant's own 60 s "fill query context" internal timeout and returned 500 errors. Cap both at 2 in `ensure_collection_with_vectors` (fresh collections) + PATCH the running collection ([runbook](docs/runbooks/qdrant-tuning.md)). Verified 60 s+ → **1.5-2.3 s hybrid mode**, well inside the 5 s MCP handler budget.
  - **No parallel bulk write clients.** The 2026-07-04 first-attempt ran Step 1 (labeling) + Step 2 (keywords) concurrently — both crashed on Qdrant timeouts within minutes. Post-bootstrap catchup phases now run strictly serial (Step 1 → 2 → 3 → ...) via sparkq `--after <job-id>` chaining. Codified in [`docs/runbooks/post-bootstrap-catchup.md`](docs/runbooks/post-bootstrap-catchup.md) §Bulk write concurrency and [`docs/design/bulk-vs-incremental-audit.md`](docs/design/bulk-vs-incremental-audit.md) §Bulk-write concurrency rule.
  - **Verified search-under-load latency profile.** With the two fixes above, 6 representative queries against the live 6.2 M-point corpus during labeling landed at 1473–2279 ms (mean ~1950 ms). All returned `mode=hybrid` (no BM25 fallback). Baseline (no bulk load) is ~400–500 ms — 3–4× slowdown during catchup but well inside the MCP handler budget and user-tolerable.

Tests: 417 → 481+ (+64 net across DQ, drain-priority, timeout, throughput bench harness). Zero regressions across the full suite.

### v0.13.2 (Jul 2026) — MCP hardening wave (post-2026-07-03 incident)

Five commits landed the day of the [2026-07-03 incident](docs/incidents/2026-07-03-mcp-search-endpoints-broken.md) postmortem, installing smoke detectors along the failure surfaces the incident exposed. Test count 382 → 417 (+35), MCP subtree 9 → 29 tests, 0 regressions.

- **`get_corpus_stats` top-N cap** (commit `f90934e`) — MCP responses were dumping all ~thousands of unique venues (1.6MB / 38K lines). New `top_venues` arg (default 30, hard cap 200) + long-tail summary `_…and <N> more venues covering <M> papers._` preserves the distribution signal. Extracted pure `format_corpus_stats()` for unit-testability. Bounded to <10KB on a 5000-venue synthetic corpus.
- **Per-handler timeout budgets** (commit `253afcf`) — Every MCP handler now runs under `asyncio.wait_for` with a strict 5s default (`_DEFAULT_HANDLER_TIMEOUT_SEC`) and per-handler overrides for legitimately-slow endpoints: `research_topic` 15s, `expand_search` 20s, `get_corpus_stats` 60s. Timeout error message names the failure mode ("query hits an unindexed payload field or a stalled backend") so future diagnosis is one message, not a debugging expedition. Refactored dispatch into a testable `_dispatch()` function separate from the SDK-decorated `call_tool` entry point.
- **`get_mcp_version` tool** (commit `2f8cf12`) — Captures `{sha, startup_ts, python}` at import time, exposes as a tool for cross-session stale-subprocess detection. Compare against `git rev-parse --short HEAD` on disk; mismatch means the MCP subprocess needs `/mcp reconnect lexiconarxiv`. Startup log emits the same fields. Graceful fallback (`sha="unknown"`) when git isn't on PATH.
- **L3 crash-safety net for embed drain** (commit `25a262a`) — Extracted the queue-consumer loop from the click command into `drain_snapshot_queue()`. Six regression tests lock in the four invariants that the 2026-06-30 663K-loss incident committed us to: mid-batch crash preserves unacked items, resume yields no duplicates, Qdrant retrieve is chunked (default 500 IDs), missing records ack cleanly.
- **SearchService fixture drift fix** (commit `880c639`) — `test_hybrid_search` was silently broken since the multi-vector migration (fixture hardcoded old single-vector schema, production has 9 dense vectors). Rebuilt from `src.core.constants.ALL_DENSE_VECTORS` — future vector additions won't drift.
- **New reference doc**: [`docs/reference/mcp-server.md`](docs/reference/mcp-server.md) — tool catalog, timeout budgets, stale-subprocess protocol, formatter contract, testing gotchas.

### v0.13.1 (Jun 2026) — Snapshot bootstrap perf hardening

- **P2 ~250× scroll speedup** via `ensure_identifier_indices()` — keyword indices on `doi`/`openalex_id`/`arxiv_id` automatically created at `ensure_collection()` and at every P2 startup. Pre-fix: every promotion did ~3 full-collection scans on a 3.6M-point corpus (~4.2s each, ~1.6K writes/hr). Post-fix: 17ms per scroll, ~75K-117K writes/hr in production. The `tests/core/snapshot/test_storage_compat.py` regression test now pins the method on real storage.
- **P2 quality gate**: `--min-cites-per-year N` (default 0) — age-normalized citation rate floor that self-balances recent vs old papers without bucket boundaries. `cited_by_count / max(1, now - pub_year) < N` drops promotion to `ENRICH_KEEP_STUB` (stub still gets enriched in place). See [docs/pipelines/stub-promotion.md](docs/pipelines/stub-promotion.md#quality-gate---min-cites-per-year).
- **`QdrantStorage.get_payload` alias** (bootstrap hotfix `5cc3bac`) bridges a mock-vs-real naming gap; new storage-compat test prevents recurrence on any phase-called method.

### v0.13.0 (Jun 2026) — Snapshot Utilization System

5 plans, 47+ commits, full quarterly + daily enrichment from the OpenAlex `works` snapshot.

- **4-phase bootstrap** (Plans 1-4): P1 metadata fill (every matched corpus paper gets ~15 missing fields), P2 stub→real promotion (preserves `cited_by` invariant), P3 hybrid gap discovery + injection (anchor + AI-concept taxonomy with age-scaled citation thresholds), P4 corpus-internal `external_cited_by` extension.
- **Live mode** (Plan 5): `snapshot-live-delta` CLI + dormant `daily_snapshot_live_schedule` chains `process_one(work)` across all 4 phases for daily OpenAlex API deltas — same phase logic as the bootstrap, different work source.
- **9 new CLIs**: 4 phase triggers + 3 operational tools (`snapshot-status`/`-reset`/`-replay-failed`) + `embed-papers --consume-snapshot-queue` + `snapshot-live-delta`.
- **5 Dagster assets**: P1 → P2 → P3 → P4 chain (`snapshot_bootstrap_job`) plus parallel `snapshot_live_delta_job`. All schedules `STOPPED` by default; operator enables after bootstrap is stable.
- **88 unit + 12 integration tests** + `tests/core/snapshot/test_storage_compat.py` (regression lock on the entire phase-call surface).
- **Operator-facing docs**: pipeline docs for each phase + Day 0..11+ bootstrap runbook + 4-scenario rollback runbook + field-mapping reference.

### v0.12.0 (Jun 2026) — Ollama-only LLMs

- Dropped Gemini (`google-genai` removed). Labeling defaults to `granite4.1:8b` (fallback `gemma4:e4b`); keyword extraction stays on `llama3.1:8b`. Embedding stays on `qwen3-embedding:8b`.
- Data quality `asset_checks` (Phases 3a/3b) cover search-critical invariants; failures block downstream Dagster assets.

### v0.11.1 (Mar 2026) — First Incremental Loop

- Collected 7,275 new papers (OpenAlex 6,089, ACL 999, DBLP 187) bringing corpus to 152K+ core papers. Full enrichment cycle completed including abstracts, citations, keywords, labeling, and embedding.
- Incremental fixes: OpenAlex Premium fallback, `force=True` for non-OpenAlex sources, S2 stub exclusion, QdrantStorage `fetched_since` passthrough, S2 `--recent-days` flag, multi-key rotation.

### v0.11.0

- **Hybrid Search**: Dense Qwen3-Embedding-8B + server-side BM25 via Qdrant Reciprocal Rank Fusion (RRF); title now included in BM25 and dense vectors
- **Search Web UI**: Interactive search at `/search` with faceted filters (venue dropdown with 21 major venues, year, tier), landing page with corpus stats and trending keywords, similar papers by section type in paper detail
- **Keyword Autocomplete**: Real-time suggestions via `GET /api/search/suggest`
- **Data Health Dashboard**: `/dashboard` with pipeline alerting (`data/core/pipeline_status.json`), data validation warnings, 5-min TTL cache
- **Rate Limiting**: 120 requests/min per IP globally
- **MCP Server**: AI agent integration via Model Context Protocol with 6 tools including `expand_search`
- **On-demand Retrieval**: Expand search results in real-time via arXiv + OpenAlex with core/connected/external labeling
- **Trends & Analytics**: Notable paper scoring, keyword time-series, rising keyword detection, UMAP+HDBSCAN topic clustering with 2D map
- **Embedding Pipeline**: Qwen3-Embedding-8B with Matryoshka Representation Learning (1024d), batch processing with collection migration

### Previous Updates (Feb 2026)

- **Code Repository Enrichment**: 3-tier strategy (PWC/HuggingFace, GROBID PDF extraction, GitHub API search) with URL classification heuristics
- **Abstract Labeling**: Sentence-level rhetorical classification (7 roles) using Ollama with structured JSON output
- **LLM-First Keywords**: Ollama as primary keyword extraction with regex + KeyBERT fallback, LLM judge validation, retry with exponential backoff
- **Graph Visualization API**: FastAPI REST API with D3.js UI for interactive citation graph exploration
- **Payload-Only Architecture**: Decouple enrichment from embeddings (see below)
- **Code Refactoring**: BaseCrawler class, BaseEnricher with mixins, centralized constants
- **Stub Papers**: Store external references for complete citation graph (no embedding)
- **Stub Deduplication**: Auto-merge duplicate stubs referenced with different identifiers (DOI/arXiv/OpenAlex)
- **Stub Enrichment**: Fetch metadata for external papers from OpenAlex/CrossRef
- **CrossRef Enrichment**: 97% success rate for ACM papers (vs 0% for Semantic Scholar)
- **Coverage Improvement**: Reference coverage increased from 73% to 89%
- **Workshop Support**: ACL workshops now collected dynamically (90+ venues)
- **OpenReview API v2**: Fixed support for ICLR 2024+, NeurIPS 2023+, ICML 2023+
- **XML Parser Fix**: Proper handling of `<fixed-case>` tags in ACL titles
- **venue_type Field**: Papers now tagged as conference/workshop/journal

## Payload-Only Architecture

LexiconArxiv uses **payload-only storage** in Qdrant, decoupling metadata collection from embeddings:

```
Collection → Enrichment → Resolution → Graph → Keywords → Labeling   (payload-only, no vectors)
                                                                ↓
                                          Migration → Embedding → BM25 Index   (Qwen3-8B 1024d + server-side BM25)
                                                                ↓
                                                       Similarity Graph   (section-level typed edges)
                                                                ↓
                                                    Hybrid Search / MCP / Trends
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Decouple pipelines** | Run full collection + enrichment without vectors |
| **Flexible dimensions** | Add embeddings later with any dimension (384, 768, 1536) |
| **Multiple vectors** | Support different embedding models via named vectors |
| **No wasted storage** | No placeholder zero vectors during collection |

> **Note**: When upserting, pass `vector={}` (empty dict) to satisfy `qdrant-client` validation.

### Adding Embeddings Later

After collection/enrichment, add vectors using Qdrant's named vectors:

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models

client = QdrantClient(url="http://localhost:6333")

# Step 1: Add vector config to existing collection
client.update_collection(
    collection_name="lexicon_arxiv",
    vectors_config={
        "abstract_embed": models.VectorParams(
            size=1536,  # OpenAI ada-002
            distance=models.Distance.COSINE,
        ),
    },
)

# Step 2: Update points with vectors (batch)
client.update_vectors(
    collection_name="lexicon_arxiv",
    points=[
        models.PointVectors(id="uuid-1", vector={"abstract_embed": embedding_1}),
        models.PointVectors(id="uuid-2", vector={"abstract_embed": embedding_2}),
    ]
)

# Step 3: Search using named vector
results = client.search(
    collection_name="lexicon_arxiv",
    query_vector=("abstract_embed", query_embedding),
    limit=10,
)
```

See [Data Model](docs/architecture/data_model.md#5-qdrant-collection-schema) for full details.

## Environment Variables

```env
OPENALEX_API_KEYS=key1,key2,key3      # Comma-separated for round-robin rotation
OPENALEX_EMAIL=your-email@example.com  # Polite-pool fallback + used by snapshot-live-delta
CROSSREF_EMAIL=your-email@example.com  # CrossRef polite pool
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=lexicon_arxiv_v3     # Production collection
OLLAMA_BASE_URL=http://localhost:11434 # Local LLM + embedding (Gemini removed in v0.12)
GITHUB_TOKEN=ghp_...                   # 30 req/min vs 10/min for code-repo search
DAGSTER_HOME=$HOME/dagster_home        # Holds snapshot phase checkpoints + embedding queue
# SNAPSHOT_DIR=/mnt/ssd/openalex_snapshot/data/works   # Only needed for snapshot bootstrap
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "Add your feature"`
4. Push to branch: `git push origin feature/your-feature`
5. Submit a Pull Request
