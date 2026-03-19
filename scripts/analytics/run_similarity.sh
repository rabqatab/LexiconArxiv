#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

K=${K:-10}
BATCH_SIZE=${BATCH_SIZE:-50}

echo "=========================================="
echo "LexiconArxiv Semantic Similarity Graph"
echo "=========================================="
echo "K: $K neighbors per edge type"
echo "Edge types: same_method, same_task, same_result, method_transfer, overall"
echo "=========================================="

uv run python -m src.cli.core_collect compute-similarity --k $K --batch-size $BATCH_SIZE "$@"

echo "=========================================="
echo "Similarity computation complete!"
echo "=========================================="
