#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "LexiconArxiv Topic Clustering"
echo "=========================================="
uv run python -m src.cli.core_collect compute-topics "$@"
echo "=========================================="
echo "Clustering complete!"
echo "=========================================="
