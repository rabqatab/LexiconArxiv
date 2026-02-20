#!/bin/bash
# Step 3.8: Enrich papers with GitHub code repository URLs
# Two-phase: PWC Archive (bulk) + HuggingFace Papers API (live)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-100}
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
            echo "Enrich papers with GitHub code repository URLs"
            echo ""
            echo "Options:"
            echo "  --parallel N          Concurrent HF API requests (default: 10)"
            echo "  --batch-size N        Batch size for updates (default: 100)"
            echo "  --retry-incomplete    Re-process papers (clears checkpoint)"
            echo "  --help                Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Code Repos] Enriching papers with GitHub repository URLs..."

CMD="uv run python -m src.cli.core_collect enrich-10-code-repos --parallel $PARALLEL --batch-size $BATCH_SIZE"
[ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
$CMD

echo "[Code Repos] Code repository enrichment complete."
