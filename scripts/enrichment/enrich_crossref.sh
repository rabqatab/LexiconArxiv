#!/bin/bash
# Step 3.2: Enrich papers via CrossRef
# Additional citation data from CrossRef API

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-5}
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
            echo "Enrich papers via CrossRef API"
            echo ""
            echo "Options:"
            echo "  --parallel N     Concurrent requests (default: 5)"
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

echo "[CrossRef] Enriching citations..."

uv run python -m src.cli.core_collect enrich-crossref --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"

echo "[CrossRef] Citation enrichment complete."
