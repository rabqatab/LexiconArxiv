#!/bin/bash
# Step 3.1: Enrich papers with DOI via OpenAlex
# For papers WITH DOIs - fetches citation data from OpenAlex

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-50}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich papers WITH DOIs via OpenAlex"
            echo ""
            echo "Options:"
            echo "  --parallel N     Concurrent requests (default: 10)"
            echo "  --batch-size N   Batch size for updates (default: 50)"
            echo "  --help           Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[OpenAlex] Enriching citations (papers with DOIs)..."

uv run python -m src.cli.core_collect enrich-citations --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"

echo "[OpenAlex] Citation enrichment complete."
