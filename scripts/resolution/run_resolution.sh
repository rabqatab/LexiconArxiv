#!/bin/bash
# Reference resolution script (Orchestrator)
# Calls individual resolution step scripts
#
# Steps:
#   4.1 Normalize - Fix identifier formats (arXiv:arXiv: -> arXiv:)
#   4.2 arXiv     - Resolve arXiv IDs to DOIs via OpenAlex
#   4.3 Internal  - Resolve all refs to internal Qdrant point IDs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
DRY_RUN=${DRY_RUN:-false}
LIMIT=${LIMIT:-0}
SKIP_NORMALIZE=${SKIP_NORMALIZE:-false}
SKIP_ARXIV=${SKIP_ARXIV:-false}
SKIP_INTERNAL=${SKIP_INTERNAL:-false}

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
        --skip-normalize)
            SKIP_NORMALIZE=true
            shift
            ;;
        --skip-arxiv)
            SKIP_ARXIV=true
            shift
            ;;
        --skip-internal)
            SKIP_INTERNAL=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Run reference resolution pipeline"
            echo ""
            echo "Steps:"
            echo "  4.1 Normalize - Fix identifier formats"
            echo "  4.2 arXiv     - Resolve arXiv IDs to DOIs"
            echo "  4.3 Internal  - Resolve refs to internal IDs"
            echo ""
            echo "Options:"
            echo "  --dry-run        Preview changes without applying"
            echo "  --limit N        Limit papers to process (0 = unlimited)"
            echo "  --skip-normalize Skip Step 4.1: Normalize"
            echo "  --skip-arxiv     Skip Step 4.2: arXiv resolution"
            echo "  --skip-internal  Skip Step 4.3: Internal resolution"
            echo "  --help           Show this help message"
            echo ""
            echo "Individual scripts:"
            echo "  ./scripts/resolution/resolve_normalize.sh"
            echo "  ./scripts/resolution/resolve_arxiv.sh"
            echo "  ./scripts/resolution/resolve_internal.sh"
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
echo "Dry Run: $DRY_RUN"
echo "Limit: $LIMIT"
echo "Skip Normalize: $SKIP_NORMALIZE"
echo "Skip arXiv: $SKIP_ARXIV"
echo "Skip Internal: $SKIP_INTERNAL"
echo "=========================================="
echo ""

# Build common args
COMMON_ARGS=""
if [ "$DRY_RUN" = true ]; then
    COMMON_ARGS="$COMMON_ARGS --dry-run"
fi
if [ "$LIMIT" -gt 0 ]; then
    COMMON_ARGS="$COMMON_ARGS --limit $LIMIT"
fi

# Step 4.1: Normalize
if [ "$SKIP_NORMALIZE" = false ]; then
    echo "--- [4.1/3] Normalize ---"
    "$SCRIPT_DIR/resolve_normalize.sh" $COMMON_ARGS
    echo ""
else
    echo "--- [4.1/3] Normalize (SKIPPED) ---"
    echo ""
fi

# Step 4.2: arXiv
if [ "$SKIP_ARXIV" = false ]; then
    echo "--- [4.2/3] arXiv ---"
    "$SCRIPT_DIR/resolve_arxiv.sh" $COMMON_ARGS
    echo ""
else
    echo "--- [4.2/3] arXiv (SKIPPED) ---"
    echo ""
fi

# Step 4.3: Internal
if [ "$SKIP_INTERNAL" = false ]; then
    echo "--- [4.3/3] Internal ---"
    "$SCRIPT_DIR/resolve_internal.sh" $COMMON_ARGS
    echo ""
else
    echo "--- [4.3/3] Internal (SKIPPED) ---"
    echo ""
fi

echo "=========================================="
echo "Resolution complete!"
echo "=========================================="

# Show reference stats
echo ""
echo "Reference Statistics:"
uv run python -m src.cli.core_collect ref-stats
