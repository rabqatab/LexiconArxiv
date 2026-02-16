#!/bin/bash
# Stage 7: Label abstract sentences with rhetorical roles
# Classifies abstract sentences into categories (background, objective, method, result, conclusion)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
BATCH_SIZE=${BATCH_SIZE:-100}
FORCE=${FORCE:-false}
LLM_BACKEND=${LLM_BACKEND:-""}
LIMIT=${LIMIT:-0}
DRY_RUN=${DRY_RUN:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --llm-backend)
            LLM_BACKEND="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Stage 7: Label abstract sentences with rhetorical roles"
            echo ""
            echo "Classifies abstract sentences into rhetorical categories"
            echo "(background, objective, method, result, conclusion)."
            echo "Papers with existing labels are skipped unless --force is used."
            echo ""
            echo "Options:"
            echo "  --batch-size N       Batch size (default: 100)"
            echo "  --llm-backend NAME   LLM backend: gemini (default) or ollama"
            echo "  --force              Re-label all papers (replace existing)"
            echo "  --limit N            Max papers to process (0 = unlimited)"
            echo "  --dry-run            Preview without saving"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Labeling] Labeling abstract sentences..."

CMD="uv run python -m src.cli.core_collect label-abstracts --batch-size $BATCH_SIZE"

[ "$FORCE" = true ] && CMD="$CMD --force"
[ -n "$LLM_BACKEND" ] && CMD="$CMD --llm-backend $LLM_BACKEND"
[ "$LIMIT" -gt 0 ] 2>/dev/null && CMD="$CMD --limit $LIMIT"
[ "$DRY_RUN" = true ] && CMD="$CMD --dry-run"

$CMD

echo "[Labeling] Complete."
