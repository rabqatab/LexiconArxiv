#!/bin/bash
# Step 4.3: Resolve references to internal Qdrant point IDs
# Links references to papers in the collection

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
DRY_RUN=${DRY_RUN:-false}
LIMIT=${LIMIT:-0}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Step 4.3: Resolve references to internal IDs"
            echo ""
            echo "Matches reference DOIs/arXiv IDs to papers in"
            echo "the Qdrant collection and sets internal_id field."
            echo ""
            echo "Options:"
            echo "  --dry-run    Preview changes without applying"
            echo "  --limit N    Limit papers to process (0 = unlimited)"
            echo "  --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Internal] Resolving references to internal IDs..."

CMD="uv run python -m src.cli.core_collect resolve-refs --step internal"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[Internal] Complete."
