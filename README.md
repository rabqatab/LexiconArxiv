# LexiconArxiv

AI Research Insights Engine - Hybrid semantic search, on-demand retrieval, trends analytics, and MCP integration for top-tier AI/ML/NLP research papers.

## Features

- **Hybrid Search**: Dense vector (Qwen3-Embedding-8B) + server-side BM25 via Qdrant Reciprocal Rank Fusion
- **Search Web UI**: Interactive search interface at `/search` with faceted filtering
- **MCP Server**: AI agent integration via Model Context Protocol (`search_papers`, `get_paper`, `get_citations`, `get_corpus_stats` tools)
- **On-demand Retrieval**: User-triggered arXiv + OpenAlex expansion with core/connected/external labeling
- **Trends & Analytics**: Notable paper scoring, keyword trends, rising keywords, UMAP+HDBSCAN topic clustering, and 2D topic map
- **Embedding Pipeline**: Qwen3-Embedding-8B embeddings (1024d via Matryoshka Representation Learning), server-side BM25 index
- **Multi-source Collection**: Collect papers from 6+ academic sources
- **27+ Main Venues**: Tier 0/1/2 conferences and journals
- **90+ Workshops**: ACL-affiliated workshop papers
- **Cross-source Deduplication**: Automatic duplicate detection
- **Checkpoint Resume**: Resumable collection with progress tracking
- **Qdrant Integration**: Payload-only storage with optional named vectors
- **Keyword Extraction**: LLM-first (Gemini/Ollama) with regex + KeyBERT fallback + LLM judge for BM25 search
- **Abstract Labeling**: LLM-based sentence classification into 7 rhetorical roles (task, domain, background, approach, method, result, contribution)
- **Citation Graph**: Reference resolution and GraphRAG support
- **Graph Visualization API**: REST API + D3.js UI for interactive citation graph exploration
- **Stub Papers**: Store external references with automatic deduplication for complete citation graph

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
# Migrate collection to add vector config (creates lexicon_arxiv_v2)
uv run python -m src.cli.core_collect migrate-collection

# Update .env to use the new collection
# QDRANT_COLLECTION=lexicon_arxiv_v2

# Run embedding pipeline (Qwen3-Embedding-8B, 1024d)
scripts/embedding/run_embedding.sh
```

### API & Search

```bash
# Start the API server
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Search UI
open http://localhost:8000/search

# Trends dashboard
open http://localhost:8000/trends

# Graph visualization
open http://localhost:8000

# API documentation (Swagger UI)
open http://localhost:8000/docs
```

**Search & Retrieval Endpoints**:
- `POST /api/search` - Hybrid search (dense + BM25 fusion) with venue/year/tier filters
- `POST /api/search/expand` - On-demand expansion via arXiv + OpenAlex
- `GET /api/paper/{paper_id}` - Full paper detail
- `GET /api/stats` - Corpus statistics

**Trends & Analytics Endpoints**:
- `GET /api/trends/notable` - Top papers ranked by notable score
- `GET /api/trends/keywords` - Keyword frequency time-series
- `GET /api/trends/rising` - Fastest-growing keywords
- `GET /api/trends/topics` - UMAP+HDBSCAN topic clusters
- `GET /api/trends/map` - 2D topic map coordinates

**Graph Endpoints**:
- `GET /graph/health` - Health check
- `GET /graph/stats` - Graph statistics
- `GET /graph/paper/{paper_id}` - Paper details
- `GET /graph/subgraph/{paper_id}?hops=1&direction=both` - Citation subgraph (D3.js format)

**Visualization Features**:
- Interactive force-directed citation graph with D3.js
- Color-coded edges (cyan=citing, orange=cited, gray=other)
- Click nodes to explore neighborhoods
- Adjustable hops (1-3) and direction

### MCP Server (AI Agent Integration)

```bash
# Start the MCP server (stdio transport)
uv run python -m src.mcp.server
```

Exposes four tools for AI agents via the Model Context Protocol:
- `search_papers` - Hybrid search with venue/year/tier filters
- `get_paper` - Lookup by UUID, DOI, or arXiv ID
- `get_citations` - Citation relationships (refs, cited_by, both)
- `get_corpus_stats` - Corpus summary statistics

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
uv run python -m src.cli.core_collect label-abstracts --limit 100          # Label papers
uv run python -m src.cli.core_collect label-abstracts --llm-backend ollama # Use Ollama
uv run python -m src.cli.core_collect label-abstracts --force --limit 50   # Re-label
```

## Documentation

- [Crawling Guide](docs/guides/crawling.md) - Detailed collection guide
- [BM25 & Hybrid Search Guide](docs/guides/bm25_hybrid_search.md) - Keyword extraction and hybrid search setup
- [Data Collection Design](docs/pipelines/data_collection.md) - Architecture and strategy
- [Keyword Extraction](docs/pipelines/keyword_extraction.md) - LLM-first keyword pipeline
- [Abstract Labeling](docs/pipelines/abstract_labeling.md) - Sentence-level rhetorical classification
- [Graph API Specification](docs/architecture/api.md#8-graph-visualization-api) - Graph Visualization API
- [Full Documentation](docs/README.md) - Complete documentation index

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
│   ├── core/                    # Core modules
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
│   │   │   ├── gemini.py        # Gemini API extraction + judge
│   │   │   ├── ollama.py        # Ollama REST API extraction + judge
│   │   │   └── judge.py         # KeywordJudge wrapper
│   │   └── labeling/            # Abstract sentence labeling
│   │       ├── labeler.py       # AbstractLabeler orchestrator (pysbd + LLM)
│   │       ├── llm_base.py      # Models, prompts, helpers, ABC
│   │       ├── gemini.py        # Gemini API labeling (round-robin)
│   │       └── ollama.py        # Ollama REST API labeling
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

## Recent Updates (Mar 2026) — v0.11.0

- **Hybrid Search**: Dense Qwen3-Embedding-8B + server-side BM25 via Qdrant Reciprocal Rank Fusion (RRF)
- **Search Web UI**: Interactive search at `/search` with faceted filters (venue, year, tier)
- **MCP Server**: AI agent integration via Model Context Protocol with 4 tools (search_papers, get_paper, get_citations, get_corpus_stats)
- **On-demand Retrieval**: Expand search results in real-time via arXiv + OpenAlex with core/connected/external labeling
- **Trends & Analytics**: Notable paper scoring, keyword time-series, rising keyword detection, UMAP+HDBSCAN topic clustering with 2D map
- **Embedding Pipeline**: Qwen3-Embedding-8B with Matryoshka Representation Learning (1024d), batch processing with collection migration

### Previous Updates (Feb 2026)

- **Code Repository Enrichment**: 3-tier strategy (PWC/HuggingFace, GROBID PDF extraction, GitHub API search) with URL classification heuristics
- **Abstract Labeling**: Sentence-level rhetorical classification (7 roles) using Gemini/Ollama with structured JSON output
- **Multi-Key Gemini**: Round-robin rotation across multiple comma-separated Gemini API keys for rate limit distribution
- **LLM-First Keywords**: Gemini/Ollama as primary keyword extraction with regex + KeyBERT fallback, LLM judge validation, retry with exponential backoff
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
OPENALEX_EMAIL=your-email@example.com  # Fallback polite pool when all keys exhausted
CROSSREF_EMAIL=your-email@example.com  # Recommended for CrossRef polite pool
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=lexicon_arxiv        # Optional, default collection name
GEMINI_API_KEYS=key1,key2,...           # Comma-separated for round-robin (keywords + labeling)
OLLAMA_BASE_URL=http://localhost:11434 # Local LLM (default)
GITHUB_TOKEN=ghp_...                   # GitHub token for code repo search (30 req/min vs 10/min)
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "Add your feature"`
4. Push to branch: `git push origin feature/your-feature`
5. Submit a Pull Request
