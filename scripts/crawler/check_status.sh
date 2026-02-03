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
echo "Available Venues"
echo "=========================================="
echo ""

echo "--- OpenAlex Venues ---"
uv run python -m src.cli.core_collect list-venues | head -20

echo ""
echo "--- ACL Anthology Venues ---"
uv run python -m src.cli.core_collect list-acl-venues

echo ""
echo "--- DBLP Venues ---"
uv run python -m src.cli.core_collect list-dblp-venues
