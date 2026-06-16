#!/bin/bash
# Step 3.9: Extract GitHub code repo URLs from paper PDFs via GROBID
# GROBID is started automatically if not already running (see
# scripts/lib/ensure_grobid.sh) and stopped on exit if this script started it.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-20}
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
            echo "GROBID is auto-started if not already running, and stopped"
            echo "on exit if this script started it."
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

# Ensure GROBID is up — auto-starts a container if needed and stops it on exit
# only if we started it (a pre-existing GROBID is left running). Honors the
# GROBID_URL parsed above. Dry-run only counts, so skip the spin-up.
source "$SCRIPT_DIR/../lib/ensure_grobid.sh"
if [ "$DRY_RUN" != true ]; then
    ensure_grobid
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
