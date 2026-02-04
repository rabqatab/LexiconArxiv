# LexiconArxiv

AI Research Insights Engine - Core Corpus collection and semantic search for top-tier AI/ML/NLP research papers.

## Features

- **Multi-source Collection**: Collect papers from 6+ academic sources
- **27+ Main Venues**: Tier 0/1/2 conferences and journals
- **90+ Workshops**: ACL-affiliated workshop papers
- **Cross-source Deduplication**: Automatic duplicate detection
- **Checkpoint Resume**: Resumable collection with progress tracking
- **Qdrant Integration**: Vector database storage for semantic search

## Quick Start

### Prerequisites

```bash
# Python 3.11+
python --version

# Start Qdrant (vector database)
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

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
python -m src.cli.core_collect init-storage
```

### Collection

```bash
# Collect from all sources (recommended)
python -m src.cli.core_collect collect-all-sources --since-year 2020

# Include workshop papers
python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Collect specific source
python -m src.cli.core_collect collect-acl --all --include-workshops
python -m src.cli.core_collect collect-openreview --all
python -m src.cli.core_collect collect-acm --all

# Check status
python -m src.cli.core_collect status
```

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
python -m src.cli.core_collect list-venues
python -m src.cli.core_collect list-acl-venues
python -m src.cli.core_collect list-openreview-venues

# Collection commands
python -m src.cli.core_collect collect-all-sources [options]
python -m src.cli.core_collect collect-acl [options]
python -m src.cli.core_collect collect-openreview [options]
python -m src.cli.core_collect collect-acm [options]
python -m src.cli.core_collect collect-dblp [options]
python -m src.cli.core_collect collect-aaai [options]

# Maintenance
python -m src.cli.core_collect status
python -m src.cli.core_collect deduplicate --dry-run
python -m src.cli.core_collect clear-checkpoint

# Enrichment (add citations/abstracts)
python -m src.cli.core_collect enrich-citations --parallel 10
python -m src.cli.core_collect enrich-abstracts --parallel 10

# Reference Resolution (build citation graph)
python -m src.cli.core_collect ref-stats
python -m src.cli.core_collect resolve-refs

# Citation Graph Analysis
python -m src.cli.core_collect citation-graph-stats
python -m src.cli.core_collect build-citation-graph -o graph.json
python -m src.cli.core_collect analyze-citation-graph --all --top-n 10
python -m src.cli.core_collect get-citing-papers <paper_id>
python -m src.cli.core_collect build-cited-by  # Required for GraphRAG
```

## Documentation

- [Crawling HOWTO](docs/guides/crawling_howto.md) - Detailed collection guide
- [Data Collection Design](docs/design/data_collection.md) - Architecture and strategy
- [Full Documentation](docs/README.md) - Complete documentation index

## Project Structure

```
lexiconarxiv/
├── src/
│   ├── cli/                     # CLI tools
│   │   └── core_collect.py      # Main collection CLI
│   ├── core/                    # Core modules
│   │   ├── storage.py           # Qdrant vector database
│   │   ├── checkpoint.py        # Resume support
│   │   ├── config.py            # Venue configurations
│   │   ├── deduplication.py     # Cross-source dedup
│   │   ├── crawler/             # Data source crawlers
│   │   │   ├── openalex.py
│   │   │   ├── acl_anthology.py
│   │   │   ├── openreview.py
│   │   │   ├── acm_open.py
│   │   │   ├── dblp.py
│   │   │   └── aaai_ojs.py
│   │   ├── enrichment/          # Enrichment pipelines
│   │   │   ├── openalex.py      # Citation/abstract via OpenAlex
│   │   │   ├── semantic_scholar.py  # S2 fallback
│   │   │   └── pdf.py           # PDF reference extraction
│   │   └── resolution/          # Reference resolution
│   │       ├── normalizer.py    # ID normalization (DOI, arXiv, OpenAlex)
│   │       └── resolver.py      # Citation graph builder
│   └── models/
│       └── paper.py             # Paper data model
├── docs/                        # Documentation
├── tests/                       # Test suite
└── data/core/checkpoints/       # Collection state
```

## Recent Updates (Feb 2026)

- **Workshop Support**: ACL workshops now collected dynamically (90+ venues)
- **OpenReview API v2**: Fixed support for ICLR 2024+, NeurIPS 2023+, ICML 2023+
- **XML Parser Fix**: Proper handling of `<fixed-case>` tags in ACL titles
- **venue_type Field**: Papers now tagged as conference/workshop/journal

## Environment Variables

```env
OPENALEX_EMAIL=your-email@example.com  # Required for polite pool
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
