#!/bin/bash
# Reference resolution script
# Builds citation graph by resolving identifiers to internal paper IDs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
STEP=${STEP:-"all"}
DRY_RUN=${DRY_RUN:-false}
LIMIT=${LIMIT:-0}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --step)
            STEP="$2"
            shift 2
            ;;
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
            echo "Options:"
            echo "  --step STEP      Run specific step: normalize, arxiv, internal, all (default: all)"
            echo "  --dry-run        Preview changes without applying"
            echo "  --limit N        Limit papers to process (0 = unlimited)"
            echo "  --help           Show this help message"
            echo ""
            echo "Steps:"
            echo "  normalize  - Fix identifier formats (arXiv:arXiv: -> arXiv:)"
            echo "  arxiv      - Resolve arXiv IDs to DOIs via OpenAlex"
            echo "  internal   - Resolve all refs to internal Qdrant point IDs"
            echo "  all        - Run all steps in sequence"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Reference Resolution"
echo "=========================================="
echo "Step: $STEP"
echo "Dry Run: $DRY_RUN"
echo "Limit: $LIMIT"
echo "=========================================="
echo ""

# Build command
CMD="uv run python -m src.cli.core_collect resolve-refs"

if [ "$STEP" != "all" ]; then
    CMD="$CMD --step $STEP"
fi

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

echo "Running: $CMD"
echo ""

# Run resolution
$CMD

echo ""
echo "=========================================="
echo "Resolution complete!"
echo "=========================================="

# Show reference stats
echo ""
echo "Reference Statistics:"
uv run python -m src.cli.core_collect ref-stats
