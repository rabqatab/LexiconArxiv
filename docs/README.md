# LexiconArxiv Documentation

**AI Research Insights Engine - Core + On-demand Architecture**

> An engine that uses top-tier research as anchors to reveal research trends, citation graphs, and notable papers.

---

## Documentation Index

### Product

| Document | Description |
|----------|-------------|
| [PRD](./prd.md) | Product Requirements Document |

### Architecture

| Document | Description |
|----------|-------------|
| [Overview](./architecture/overview.md) | System architecture design |
| [Data Model](./architecture/data_model.md) | Database schema and data models |
| [API Specification](./architecture/api.md) | REST API and MCP interface spec |

### Pipelines

| Document | Description |
|----------|-------------|
| [Data Collection](./pipelines/data_collection.md) | Multi-source data collection strategy |
| [Incremental Crawling](./pipelines/incremental_crawling.md) | Incremental update strategy and troubleshooting |
| [Enrichment](./pipelines/enrichment.md) | Citation and abstract enrichment (covers P1 metadata fill) |
| [Embedding](./pipelines/embedding.md) | Qwen3-Embedding-8B + section vectors + BM25 |
| [Keyword Extraction](./pipelines/keyword_extraction.md) | Keyword/acronym extraction for BM25 |
| [Abstract Labeling](./pipelines/abstract_labeling.md) | Abstract sentence rhetorical classification |
| [Citation Graph](./pipelines/citation_graph.md) | Citation graph + GraphRAG (covers P4 external_cited_by) |
| [Stub Promotion](./pipelines/stub-promotion.md) | P2: snapshot-driven stub → real paper promotion |
| [Corpus Gap Discovery](./pipelines/corpus-gap-discovery.md) | P3: hybrid-classified injection (anchor + AI taxonomy) |
| [Snapshot Live Mode](./pipelines/snapshot-live-mode.md) | Daily OpenAlex API delta — same phase chain as bootstrap |
| [Search](./pipelines/search.md) | Hybrid search pipeline |

### Guides

| Document | Description |
|----------|-------------|
| [Quick Start](./guides/quickstart.md) | Complete setup and pipeline execution |
| [Crawling](./guides/crawling.md) | Detailed crawling guide |
| [BM25 Migration](./guides/bm25_migration.md) | Enable hybrid search (dense + BM25) |
| [Troubleshooting](./guides/troubleshooting.md) | Common issues and solutions |

### Reference

| Document | Description |
|----------|-------------|
| [Venues](./reference/venues.md) | Venue tiers, IDs, and classifications |
| [CLI](./reference/cli.md) | Complete CLI command reference |
| [Snapshot Field Mapping](./reference/snapshot-fields.md) | OpenAlex `works` JSONL → Qdrant payload mapping |
| [Labeling LLM Comparison](./reference/labeling-llm-comparison.md) | granite4.1:8b vs gemma4:e4b vs DiffusionGemma eval results |

### Runbooks

| Document | Description |
|----------|-------------|
| [Snapshot Bootstrap](./runbooks/snapshot-bootstrap.md) | Day 0..11+ procedure for quarterly snapshot ingest (P1→P2→P3→P4 + Day 12+ live-mode enable) |
| [Snapshot Rollback](./runbooks/snapshot-rollback.md) | 4 scenarios: P2 wrong promotions, P3 injection runaway, Qdrant corruption, embedding queue lost |
| [Dagster Cutover](./runbooks/dagster-cutover.md) | Migrating from bash orchestration to Dagster |

### Specs & Plans

| Document | Description |
|----------|-------------|
| [Snapshot Utilization Design](./superpowers/specs/2026-06-21-snapshot-utilization-design.md) | 5-plan architecture for OpenAlex snapshot bootstrap + live mode |
| [Plan TODO](./plans/TODO.md) | Live backlog and deferred items |
| [Ponytail Audit (2026-06-24)](./refactoring/2026-06-24-ponytail-audit.md) | Over-engineering audit — ~1800 lines / 4 deps removable, deferred until post-bootstrap |

### Incidents

| Document | Date | Severity | Summary |
|----------|------|----------|---------|
| [P2 missing payload indices](./incidents/2026-06-29-p2-missing-payload-indices.md) | 2026-06-29 | High | Bootstrap P2 throughput collapsed to 1.6K writes/hr (260h linear ETA) because `doi`/`openalex_id`/`arxiv_id` lacked Qdrant indices → every promotion did 3 full-collection scans. Fixed with auto-called `ensure_identifier_indices()`; production throughput restored to 225K writes/hr (140×). |

### Testing & Design

| Document | Description |
|----------|-------------|
| [Testing Strategy](./testing/strategy.md) | Test strategy and quality assurance |
| [UX Design](./design/ux.md) | UI/UX design |

---

## Core Concepts

- **Core Corpus**: Pre-collected papers from Tier 0/1/2 venues (27 main venues + 90+ workshops)
- **On-demand**: Real-time arXiv/OpenAlex search at query time
- **Core Connection**: Display citation/similarity relationships between on-demand papers and Core
- **Research Graph**: Citation network visualization between papers
- **Graph Visualization API**: REST API for interactive citation graph exploration with D3.js UI
- **Stub Papers**: External papers referenced by corpus papers but not crawled (for complete citation graph)
- **Payload-Only Storage**: Decouple metadata from embeddings; add vectors later with any dimension
- **Snapshot Bootstrap (quarterly)**: 4-phase enrichment from a local OpenAlex `works` snapshot — fill metadata, promote stubs, inject AI-relevant gaps, extend external_cited_by
- **Snapshot Live Mode (daily)**: Same `process_one(work)` chain driven by the OpenAlex API delta — keeps the corpus current between quarterly bootstraps

### Venue Summary

| Tier | Count | Description |
|------|-------|-------------|
| Tier 0 | 11 | Top-tier venues (NeurIPS, ICML, ICLR, ACL, EMNLP, etc.) |
| Tier 1 | 14 | Extended venues (NAACL, EACL, COLING, WSDM, etc.) |
| Tier 2 | 3+ | Specialized + 90+ workshops |

See [Venue Reference](./reference/venues.md) for complete details.

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/your-org/lexiconarxiv.git
cd lexiconarxiv
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # Edit with OPENALEX_EMAIL

# Start Qdrant
docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant

# Run full pipeline
uv run python -m src.cli.core_collect init-storage
./scripts/run_full_pipeline.sh --since-year 2018 --include-workshops

# Check status
uv run python -m src.cli.core_collect status

# Start Graph Visualization API
uv run uvicorn src.api.main:app --reload --port 8000
# Open http://localhost:8000 for visualization UI
```

See [Quick Start Guide](./guides/quickstart.md) for detailed instructions.

---

## Project Structure

```
lexiconarxiv/
├── docs/                        # Documentation (this directory)
│   ├── architecture/            # System architecture
│   ├── pipelines/               # Data processing pipelines
│   ├── guides/                  # How-to guides
│   ├── reference/               # Reference material
│   ├── testing/                 # Test strategy
│   └── design/                  # UI/UX design
├── src/
│   ├── api/                     # Graph Visualization API
│   │   ├── main.py              # FastAPI app with lifespan
│   │   ├── dependencies.py      # GraphServices singleton
│   │   ├── routes/graph.py      # /graph/* endpoints
│   │   ├── models/responses.py  # Pydantic response models
│   │   └── static/index.html    # D3.js visualization UI
│   ├── orchestration/           # Dagster: assets, jobs, schedules, asset_checks (DQ)
│   ├── core/                    # Core Corpus collection
│   │   ├── crawler/             # Data source collectors
│   │   ├── enrichment/          # Citation/abstract enrichment
│   │   ├── resolution/          # Reference resolution
│   │   ├── citation_graph/      # Graph building and analysis
│   │   ├── snapshot/            # OpenAlex snapshot bootstrap (Plans 1-5)
│   │   │   ├── phase{1,2,3,4}_*.py       # P1/P2/P3/P4 phase modules
│   │   │   ├── live_worker.py            # daily API delta chain
│   │   │   ├── work_source.py            # iter_snapshot_works + iter_live_works
│   │   │   ├── gap_filter.py             # AI taxonomy classification (P3)
│   │   │   ├── matcher.py / promotion.py # DOI/arXiv/title matching, stub merge
│   │   │   └── checkpoint.py / embedding_queue.py / stats.py / extractor.py
│   │   ├── keyword/             # Keyword extraction (Ollama)
│   │   └── labeling/            # Abstract sentence labeling (Ollama)
│   ├── models/                  # Data models
│   ├── cli/                     # CLI tools
│   └── utils/                   # Utilities
├── tests/
├── data/core/checkpoints/       # Collection checkpoints
└── scripts/crawler/             # Collection scripts
```

---

## Tech Stack

```
Backend:        Python 3.12+ / FastAPI / uvicorn
Vector store:   Qdrant (payload-only, named vectors, server-side BM25)
LLM:            Ollama-only (Gemini removed v0.12)
                - granite4.1:8b (labeling, default; fallback gemma4:e4b)
                - llama3.1:8b (keyword extraction)
                - qwen3-embedding:8b (1024d via Matryoshka)
ML/NLP:         sentence-transformers (Qwen3-Reranker-0.6B) / KeyBERT
Orchestration:  Dagster (assets, jobs, schedules, asset_checks for DQ)
Snapshot:       OpenAlex `works` JSONL (~600GB gzip, quarterly) + daily API delta
Graph:          NetworkX (citation graph) / D3.js (visualization)
Infra:          Docker (Qdrant, GROBID) / Kubernetes (optional)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.13.1 | Jun 2026 | P2 perf hardening: `ensure_identifier_indices()` (~250x scroll speedup), `--min-cites-per-year` age-normalized quality gate, get_payload alias hotfix + compat regression test |
| 0.13.0 | Jun 2026 | Snapshot Utilization System (5 plans, 47+ commits): 4-phase bootstrap (metadata fill / stub promotion / gap injection / external_cited_by) + live mode (daily OpenAlex API delta) + 9 CLIs + 5 Dagster assets + 3 dormant schedules + 88 unit/12 integration tests |
| 0.12.0 | Jun 2026 | Ollama-only LLMs — Gemini removed; labeling defaults to granite4.1:8b; data quality asset_checks (Phase 3a/3b) cover search-critical invariants |
| 0.11.1 | Mar 2026 | First incremental loop (152K papers), OpenAlex Premium fallback, multi-key rotation |
| 0.11.0 | Mar 2026 | Hybrid search (Qwen3-8B + BM25 RRF), search/dashboard UIs, MCP server, on-demand retrieval, trends + UMAP+HDBSCAN topic clusters |
| 0.10.0 | Feb 2026 | Abstract sentence labeling (7 rhetorical roles), multi-key Gemini round-robin (deprecated in v0.12) |
| 0.9.0 | Feb 2026 | LLM-enhanced keyword extraction (Gemini/Ollama), LLM judge validation, configurable embeddings |
| 0.8.0 | Feb 2026 | Graph Visualization API with D3.js UI for citation graph exploration |
| 0.7.2 | Feb 2026 | DBLP/ACM consolidation, build_cited_by retry fix, incremental pipeline script |
| 0.7.1 | Feb 2026 | ACL Git Trees API fix, NeurIPS D&B track, AACL venue, incremental docs |
| 0.7.0 | Feb 2026 | Payload-only architecture, named vectors support |
| 0.6.3 | Feb 2026 | Crawler base class, centralized API constants, checkpoint mixin |
| 0.6.2 | Feb 2026 | Refactored enrichment modules with shared base classes |
| 0.6.1 | Feb 2026 | Stub enrichment with cross-reference deduplication |
| 0.6.0 | Feb 2026 | Stub papers for complete citation graph, CrossRef enrichment |
| 0.5.0 | Feb 2026 | Keyword extraction (Regex + KeyBERT) for BM25 search |
| 0.4.1 | Feb 2026 | ACL workshop support, OpenReview API v2 fix |
| 0.4.0 | Feb 2026 | Multi-source crawlers (OpenReview, ACM, AAAI) |
| 0.3.0 | - | MVP-3: Saved query + API |
| 0.2.0 | - | MVP-2: ACL Anthology + embedding search |
| 0.1.0 | - | MVP-1: OpenAlex + arXiv search |

---

## Contributing

1. Create issue or check existing issues
2. Create feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "Add your feature"`
4. Create PR

### Code Style

- Python: black + isort + flake8
- Type hints required
- Docstrings (Google style)

---

## License

MIT License

---

## Contact

- GitHub Issues: [link]
- Email: team@lexiconarxiv.io
