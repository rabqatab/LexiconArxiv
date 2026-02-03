#!/bin/bash
# Deduplication script
# Removes duplicate papers across data sources

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
DRY_RUN=${DRY_RUN:-true}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --apply)
            DRY_RUN=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run    Preview duplicates without removing (default)"
            echo "  --apply      Actually remove duplicates"
            echo "  --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Deduplication"
echo "=========================================="
echo "Dry Run: $DRY_RUN"
echo "=========================================="
echo ""

# Build command
CMD="uv run python -m src.cli.core_collect deduplicate"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

echo "Running: $CMD"
echo ""

# Run deduplication
$CMD

echo ""
echo "=========================================="
echo "Deduplication complete!"
echo "=========================================="
