#!/bin/bash
# Step 3.4: Enrich papers with missing abstracts
# Fetches abstracts from OpenAlex for papers missing them

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-50}
RETRY_INCOMPLETE=false

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
        --retry-incomplete)
            RETRY_INCOMPLETE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich papers with missing abstracts"
            echo ""
            echo "Options:"
            echo "  --parallel N          Concurrent requests (default: 10)"
            echo "  --batch-size N        Batch size for updates (default: 50)"
            echo "  --retry-incomplete    Re-process papers still missing data"
            echo "  --help                Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Abstracts] Enriching missing abstracts..."

CMD="uv run python -m src.cli.core_collect enrich-abstracts --parallel $PARALLEL --batch-size $BATCH_SIZE"
[ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
$CMD

echo "[Abstracts] Enrichment complete."
