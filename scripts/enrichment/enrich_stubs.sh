#!/bin/bash
# Step 3.5: Enrich stub papers with metadata
# Fetches metadata for stub papers (external references)
#
# NOTE: This is an expensive operation (187K+ stubs).
# Run separately from main enrichment pipeline.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-5}
LIMIT=${LIMIT:-0}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich stub papers with metadata"
            echo ""
            echo "NOTE: Expensive operation (187K+ stubs)."
            echo "      Consider using --limit for testing."
            echo ""
            echo "Options:"
            echo "  --parallel N  Concurrent requests (default: 5)"
            echo "  --limit N     Limit papers to process (0 = unlimited)"
            echo "  --help        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Stubs] Enriching stub papers..."

CMD="uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --parallel $PARALLEL"

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[Stubs] Enrichment complete."
