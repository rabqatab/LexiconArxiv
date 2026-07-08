"""Core corpus collection module for LexiconArxiv.

Subpackages:
- crawler/     - Data source collectors (OpenAlex, ACL, DBLP, OpenReview, ACM, AAAI)
- enrichment/  - Enrichment pipelines (OpenAlex, Semantic Scholar, PDF)
- resolution/  - Reference resolution (normalizer, resolver)

Core modules:
- storage.py       - Qdrant vector database layer
- checkpoint.py    - Checkpoint management for resumable operations
- config.py        - Venue configurations
- deduplication.py - Cross-source deduplication
"""
