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
| [Enrichment](./pipelines/enrichment.md) | Citation and abstract enrichment |
| [Keyword Extraction](./pipelines/keyword_extraction.md) | Keyword/acronym extraction for BM25 |
| [Citation Graph](./pipelines/citation_graph.md) | Citation graph and GraphRAG design |
| [Search](./pipelines/search.md) | Hybrid search pipeline |

### Guides

| Document | Description |
|----------|-------------|
| [Quick Start](./guides/quickstart.md) | Complete setup and pipeline execution |
| [Crawling](./guides/crawling.md) | Detailed crawling guide |
| [Troubleshooting](./guides/troubleshooting.md) | Common issues and solutions |

### Reference

| Document | Description |
|----------|-------------|
| [Venues](./reference/venues.md) | Venue tiers, IDs, and classifications |
| [CLI](./reference/cli.md) | Complete CLI command reference |

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
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

# Run full pipeline
python -m src.cli.core_collect init-storage
./scripts/run_full_pipeline.sh --since-year 2018 --include-workshops

# Check status
python -m src.cli.core_collect status
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
│   ├── api/                     # FastAPI endpoints
│   ├── core/                    # Core Corpus collection
│   │   ├── crawler/             # Data source collectors
│   │   ├── enrichment/          # Citation/abstract enrichment
│   │   ├── resolution/          # Reference resolution
│   │   ├── citation_graph/      # Graph building and analysis
│   │   └── keyword/             # Keyword extraction
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
Backend:     Python 3.12+ / FastAPI / Celery
Databases:   PostgreSQL / Qdrant (vector + BM25)
ML/NLP:      sentence-transformers / KeyBERT / spaCy
Graph:       NetworkX (citation graph)
Infra:       Docker / Kubernetes
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
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
