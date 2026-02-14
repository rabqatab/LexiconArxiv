# LexiconArxiv

AI Research Insights Engine - Core Corpus collection and semantic search for top-tier AI/ML/NLP research papers.

## Features

- **Multi-source Collection**: Collect papers from 6+ academic sources
- **27+ Main Venues**: Tier 0/1/2 conferences and journals
- **90+ Workshops**: ACL-affiliated workshop papers
- **Cross-source Deduplication**: Automatic duplicate detection
- **Checkpoint Resume**: Resumable collection with progress tracking
- **Qdrant Integration**: Payload-only storage with optional named vectors
- **Keyword Extraction**: LLM-first (Gemini/Ollama) with regex + KeyBERT fallback + LLM judge for BM25 search
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
uv run python -m src.cli.core_collect collect-acm --all

# Check status
uv run python -m src.cli.core_collect status
```

### Graph Visualization API

```bash
# Start the API server (pre-builds citation index on startup)
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Open the visualization UI
open http://localhost:8000

# API documentation (Swagger UI)
open http://localhost:8000/docs
```

**API Endpoints**:
- `GET /graph/health` - Health check
- `GET /graph/stats` - Graph statistics
- `GET /graph/paper/{paper_id}` - Paper details
- `GET /graph/subgraph/{paper_id}?hops=1&direction=both` - Citation subgraph (D3.js format)

**Visualization Features**:
- Interactive force-directed graph with D3.js
- Color-coded edges (cyan=citing, orange=cited, gray=other)
- Click nodes to explore neighborhoods
- Adjustable hops (1-3) and direction

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
uv run python -m src.cli.core_collect collect-acm [options]
uv run python -m src.cli.core_collect collect-dblp [options]
uv run python -m src.cli.core_collect collect-aaai [options]

# Maintenance
uv run python -m src.cli.core_collect status
uv run python -m src.cli.core_collect deduplicate --dry-run
uv run python -m src.cli.core_collect clear-checkpoint

# Enrichment (add citations/abstracts)
uv run python -m src.cli.core_collect enrich-citations --parallel 10    # OpenAlex
uv run python -m src.cli.core_collect enrich-crossref --parallel 5      # CrossRef (ACM/Springer)
uv run python -m src.cli.core_collect enrich-s2                         # Semantic Scholar
uv run python -m src.cli.core_collect enrich-abstracts --parallel 10    # Abstracts

# Retry enrichment for papers still missing data after rate limits
uv run python -m src.cli.core_collect enrich-citations --retry-incomplete
uv run python -m src.cli.core_collect enrich-citations-by-title --retry-incomplete
uv run python -m src.cli.core_collect enrich-crossref --retry-incomplete

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
uv run python -m src.cli.core_collect enrich-stubs --limit 1000         # Fetch metadata for stubs

# Keyword Extraction (for BM25 search)
uv run python -m src.cli.core_collect extract-keywords --llm --judge  # LLM-first pipeline (recommended)
uv run python -m src.cli.core_collect extract-keywords              # Fallback only (regex + KeyBERT)
uv run python -m src.cli.core_collect extract-keywords --no-keybert # Regex only (faster)
uv run python -m src.cli.core_collect extract-keywords --dry-run    # Preview mode
uv run python -m src.cli.core_collect keyword-stats                 # Show statistics
```

## Documentation

- [Crawling Guide](docs/guides/crawling.md) - Detailed collection guide
- [Data Collection Design](docs/pipelines/data_collection.md) - Architecture and strategy
- [Graph API Specification](docs/architecture/api.md#8-graph-visualization-api) - Graph Visualization API
- [Full Documentation](docs/README.md) - Complete documentation index

## Project Structure

```
lexiconarxiv/
├── src/
│   ├── api/                     # Graph Visualization API
│   │   ├── main.py              # FastAPI app with lifespan
│   │   ├── dependencies.py      # GraphServices (storage, index, builder)
│   │   ├── routes/graph.py      # /graph/* endpoints
│   │   ├── models/responses.py  # Pydantic response models
│   │   └── static/index.html    # D3.js visualization UI
│   ├── cli/                     # CLI tools
│   │   ├── core_collect.py      # Main CLI entry point
│   │   └── commands/            # CLI command modules
│   ├── core/                    # Core modules
│   │   ├── storage/             # Qdrant storage package
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
│   │   │   └── pdf.py           # PDF reference extraction
│   │   ├── resolution/          # Reference resolution
│   │   │   ├── normalizer.py    # ID normalization (DOI, arXiv, OpenAlex)
│   │   │   └── resolver.py      # Citation graph builder
│   │   └── keyword/             # Keyword extraction
│   │       ├── extractor.py     # KeywordExtractor (sync + async pipeline)
│   │       ├── patterns.py      # Regex patterns for acronyms
│   │       ├── stopwords.py     # Stopword filtering
│   │       ├── llm_base.py      # Pydantic models, prompts, ABC base classes
│   │       ├── gemini.py        # Gemini API extraction + judge
│   │       ├── ollama.py        # Ollama REST API extraction + judge
│   │       └── judge.py         # KeywordJudge wrapper
│   └── models/
│       └── paper.py             # Paper data model
├── docs/                        # Documentation
├── tests/                       # Test suite
└── data/core/checkpoints/       # Collection state
```

## Recent Updates (Feb 2026)

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
Collection → Enrichment → Resolution → Graph   (payload-only, no vectors)
                                        ↓
                              Add Embeddings   (named vectors, any dimension)
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
OPENALEX_EMAIL=your-email@example.com  # Required for polite pool
CROSSREF_EMAIL=your-email@example.com  # Recommended for CrossRef polite pool
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=lexicon_arxiv        # Optional, default collection name
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "Add your feature"`
4. Push to branch: `git push origin feature/your-feature`
5. Submit a Pull Request
