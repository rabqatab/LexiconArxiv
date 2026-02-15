#!/bin/bash
# Step 3.6: Extract references from PDFs using GROBID
# Last-resort fallback when API-based enrichment fails
#
# Requires GROBID server running:
#   docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-2}
BATCH_SIZE=${BATCH_SIZE:-10}
LIMIT=${LIMIT:-0}
DRY_RUN=${DRY_RUN:-false}
GROBID_URL=${GROBID_URL:-"http://localhost:8070"}

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
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Step 3.6: Extract references from PDFs using GROBID"
            echo ""
            echo "This is the last-resort fallback for papers where"
            echo "API-based enrichment (OpenAlex, CrossRef) failed."
            echo ""
            echo "Requires GROBID server:"
            echo "  docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
            echo ""
            echo "Options:"
            echo "  --parallel N      Concurrent extractions (default: 2)"
            echo "  --batch-size N    Batch size (default: 10)"
            echo "  --limit N         Max papers to process (0 = unlimited)"
            echo "  --dry-run         Count papers without extracting"
            echo "  --grobid-url URL  GROBID server URL (default: http://localhost:8070)"
            echo "  --help            Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[PDF/GROBID] Extracting references from PDFs..."

# Check if GROBID is running
if ! curl -s --connect-timeout 5 "$GROBID_URL/api/isalive" > /dev/null 2>&1; then
    echo "[PDF/GROBID] WARNING: GROBID server not responding at $GROBID_URL"
    echo "[PDF/GROBID] Start GROBID with: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
    echo "[PDF/GROBID] Skipping PDF extraction."
    exit 0
fi

CMD="uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel $PARALLEL --batch-size $BATCH_SIZE --grobid-url $GROBID_URL"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[PDF/GROBID] Complete."
