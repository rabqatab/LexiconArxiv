#!/bin/bash
# Stage 6: Extract keywords and acronyms for BM25 search
# Default: LLM-first with judge (requires GEMINI_API_KEYS in .env)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
BATCH_SIZE=${BATCH_SIZE:-100}
USE_LLM=${USE_LLM:-true}
USE_JUDGE=${USE_JUDGE:-true}
FORCE=${FORCE:-false}
NO_KEYBERT=${NO_KEYBERT:-false}
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
        --no-llm)
            USE_LLM=false
            shift
            ;;
        --no-judge)
            USE_JUDGE=false
            shift
            ;;
        --llm-backend)
            LLM_BACKEND="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --no-keybert)
            NO_KEYBERT=true
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
            echo "Stage 6: Extract keywords and acronyms for BM25 search"
            echo ""
            echo "By default, uses LLM-first extraction with judge verification."
            echo "Papers with existing keywords are skipped unless --force is used."
            echo ""
            echo "Options:"
            echo "  --batch-size N       Batch size (default: 100)"
            echo "  --no-llm             Disable LLM extraction (regex + KeyBERT only)"
            echo "  --no-judge           Disable judge verification"
            echo "  --llm-backend NAME   LLM backend: gemini (default) or ollama"
            echo "  --force              Re-extract all papers (replace existing)"
            echo "  --no-keybert         Skip KeyBERT (regex-only fallback)"
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

echo "[Keywords] Extracting keywords and acronyms..."

CMD="uv run python -m src.cli.core_collect extract-keywords --batch-size $BATCH_SIZE"

[ "$USE_LLM" = true ] && CMD="$CMD --llm"
[ "$USE_JUDGE" = true ] && CMD="$CMD --judge"
[ "$FORCE" = true ] && CMD="$CMD --force"
[ "$NO_KEYBERT" = true ] && CMD="$CMD --no-keybert"
[ -n "$LLM_BACKEND" ] && CMD="$CMD --llm-backend $LLM_BACKEND"
[ "$LIMIT" -gt 0 ] 2>/dev/null && CMD="$CMD --limit $LIMIT"
[ "$DRY_RUN" = true ] && CMD="$CMD --dry-run"

$CMD

echo "[Keywords] Complete."
