#!/bin/bash
# Build cited_by field for GraphRAG
#
# This script builds the reverse citation index and stores it in Qdrant.
# After running, each paper will have:
#   - resolved_references: papers this paper cites
#   - cited_by: papers that cite this paper
#
# Memory usage: Low (~100 MB) - builds index in streaming fashion
# Time: ~5-10 min for 150K papers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "Build cited_by Field (for GraphRAG)"
echo "=========================================="
echo ""

# Check current status
echo "Current citation graph status:"
uv run python -m src.cli.core_collect citation-graph-stats
echo ""

# Build cited_by
echo "Building cited_by field..."
echo "(Scanning all papers and computing reverse citations)"
echo ""

uv run python -m src.cli.core_collect build-cited-by

echo ""
echo "=========================================="
echo "Complete!"
echo "=========================================="
echo ""
echo "The cited_by field is now available for all papers."
echo ""
echo "GraphRAG usage example (after adding embeddings):"
echo "  1. Query: Retrieve top K papers by embedding similarity"
echo "  2. Expand: For each paper, get resolved_references + cited_by"
echo "  3. Generate: Use expanded context for LLM generation"
echo ""
echo "Note: Embeddings are added separately via named vectors."
echo "See docs/architecture/data_model.md for details."
