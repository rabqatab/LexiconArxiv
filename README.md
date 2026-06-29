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
- **Keyword Extraction**: LLM-first (Ollama) with regex + KeyBERT fallback + LLM judge for BM25 search
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

# Keyword Extraction (for BM25 search)
uv run python -m src.cli.core_collect extract-keywords --llm --judge  # LLM-first pipeline (recommended)
uv run python -m src.cli.core_collect extract-keywords              # Fallback only (regex + KeyBERT)
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
│   │   ├── checkpoint_mixin.py  # Reusable checkpoint mixin
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
