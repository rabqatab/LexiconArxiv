#!/bin/bash
# Step 3.6: Resolve TITLE:xxx references via OpenAlex title search
# Replaces TITLE:<title> entries in referenced_works with DOI:xxx or Wxxx identifiers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-3}
BATCH_SIZE=${BATCH_SIZE:-100}
LIMIT=${LIMIT:-0}
DRY_RUN=${DRY_RUN:-false}
RETRY_INCOMPLETE=${RETRY_INCOMPLETE:-false}

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
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --retry-incomplete)
            RETRY_INCOMPLETE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Step 3.6: Resolve TITLE:xxx references via OpenAlex"
            echo ""
            echo "Resolves TITLE:<title> entries in referenced_works to"
            echo "proper DOI:xxx or Wxxx (OpenAlex) identifiers by searching"
            echo "OpenAlex and fuzzy-matching titles."
            echo ""
            echo "Options:"
            echo "  --parallel N         Concurrent requests (default: 3)"
            echo "  --batch-size N       Batch size (default: 100)"
            echo "  --limit N            Max papers to process (0 = unlimited)"
            echo "  --dry-run            Count papers without resolving"
            echo "  --retry-incomplete   Re-process papers (clears checkpoint)"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Resolve Title Refs] Resolving TITLE:xxx references via OpenAlex..."

CMD="uv run python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --parallel $PARALLEL --batch-size $BATCH_SIZE"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

if [ "$RETRY_INCOMPLETE" = true ]; then
    CMD="$CMD --retry-incomplete"
fi

$CMD

echo "[Resolve Title Refs] Complete."
