#!/bin/bash
# Step 4.2: Resolve arXiv IDs to DOIs
# Uses OpenAlex to find DOIs for arXiv references

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
            echo "Step 4.2: Resolve arXiv IDs to DOIs"
            echo ""
            echo "Queries OpenAlex to find DOIs for references"
            echo "that only have arXiv identifiers."
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

echo "[arXiv] Resolving arXiv IDs to DOIs..."

CMD="uv run python -m src.cli.core_collect resolve-refs --step arxiv"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[arXiv] Complete."
