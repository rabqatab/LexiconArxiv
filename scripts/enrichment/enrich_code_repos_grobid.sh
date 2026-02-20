#!/bin/bash
# Step 3.9: Extract GitHub code repo URLs from paper PDFs via GROBID
# Requires GROBID server running:
#   docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-5}
BATCH_SIZE=${BATCH_SIZE:-20}
LIMIT=${LIMIT:-0}
DRY_RUN=${DRY_RUN:-false}
GROBID_URL=${GROBID_URL:-"http://localhost:8070"}
RETRY_INCOMPLETE=false

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
        --grobid-url)
            GROBID_URL="$2"
            shift 2
            ;;
        --retry-incomplete)
            RETRY_INCOMPLETE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Step 3.9: Extract GitHub code repo URLs from paper PDFs via GROBID"
            echo ""
            echo "Downloads PDFs, extracts full-text via GROBID, finds and"
            echo "classifies GitHub URLs using section/context heuristics."
            echo ""
            echo "Requires GROBID server:"
            echo "  docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
            echo ""
            echo "Options:"
            echo "  --parallel N         Concurrent extractions (default: 5)"
            echo "  --batch-size N       Batch size (default: 20)"
            echo "  --limit N            Max papers to process (0 = unlimited)"
            echo "  --dry-run            Count papers without extracting"
            echo "  --grobid-url URL     GROBID server URL (default: http://localhost:8070)"
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

echo "[GROBID Code Repos] Extracting GitHub URLs from paper PDFs..."

# Check if GROBID is running
if ! curl -s --connect-timeout 5 "$GROBID_URL/api/isalive" > /dev/null 2>&1; then
    echo "[GROBID Code Repos] WARNING: GROBID server not responding at $GROBID_URL"
    echo "[GROBID Code Repos] Start GROBID with: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
    echo "[GROBID Code Repos] Skipping GROBID code repo extraction."
    exit 0
fi

CMD="uv run python -m src.cli.core_collect enrich-11-code-repos-via-grobid --parallel $PARALLEL --batch-size $BATCH_SIZE --grobid-url $GROBID_URL"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

[ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"

$CMD

echo "[GROBID Code Repos] Complete."
