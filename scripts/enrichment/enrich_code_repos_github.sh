#!/bin/bash
# Step 3.10: Search GitHub API for code repositories matching papers
# Tier A: arXiv ID in README (high precision)
# Tier B: Title search with validation heuristics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
BATCH_SIZE=${BATCH_SIZE:-50}
LIMIT=${LIMIT:-0}
DRY_RUN=${DRY_RUN:-false}
RETRY_INCOMPLETE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
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
            echo "Step 3.10: Search GitHub API for code repositories"
            echo ""
            echo "Two-tier strategy:"
            echo "  Tier A: arXiv ID in README.md (high precision)"
            echo "  Tier B: Title search with validation heuristics"
            echo ""
            echo "Rate limits: 30 req/min with GITHUB_TOKEN, 10/min without."
            echo ""
            echo "Options:"
            echo "  --batch-size N       Batch size (default: 50)"
            echo "  --limit N            Max papers to process (0 = unlimited)"
            echo "  --dry-run            Count papers without searching"
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

echo "[GitHub Search] Searching GitHub for code repositories..."

if [ -z "$GITHUB_TOKEN" ]; then
    echo "[GitHub Search] WARNING: GITHUB_TOKEN not set. Rate limit: 10 req/min."
    echo "[GitHub Search] Set GITHUB_TOKEN for 30 req/min."
fi

CMD="uv run python -m src.cli.core_collect enrich-12-code-repos-via-github --batch-size $BATCH_SIZE"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

[ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"

$CMD

echo "[GitHub Search] Complete."
