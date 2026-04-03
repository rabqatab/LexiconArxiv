#!/bin/bash
cd /home/alphabridge/LexiconArxiv
export QDRANT_COLLECTION=lexicon_arxiv_v3
exec /home/alphabridge/.local/bin/uv run python -m src.mcp.server
