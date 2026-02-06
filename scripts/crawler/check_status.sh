#!/bin/bash
# Check collection status and Qdrant storage stats

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "LexiconArxiv Collection Status"
echo "=========================================="
echo ""

uv run python -m src.cli.core_collect status

echo ""
echo "=========================================="
echo "Reference Statistics"
echo "=========================================="
echo ""

uv run python -m src.cli.core_collect ref-stats

echo ""
echo "=========================================="
echo "Available Venues"
echo "=========================================="
echo ""

echo "--- [1.1] OpenAlex Venues ---"
uv run python -m src.cli.core_collect list-venues | head -20

echo ""
echo "--- [1.2] ACL Anthology Venues ---"
uv run python -m src.cli.core_collect list-acl-venues

echo ""
echo "--- [1.3] DBLP Venues ---"
uv run python -m src.cli.core_collect list-dblp-venues

echo ""
echo "--- [1.4] OpenReview Venues ---"
uv run python -m src.cli.core_collect list-openreview-venues

echo ""
echo "--- [1.5] ACM Venues ---"
uv run python -m src.cli.core_collect list-acm-venues

echo ""
echo "--- [1.6] AAAI Venues ---"
uv run python -m src.cli.core_collect list-aaai-venues
