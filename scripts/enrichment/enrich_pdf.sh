#!/bin/bash
# Step 3.5: Extract references and abstracts from PDFs using GROBID
# Last-resort fallback when API-based enrichment fails
#
# Runs:
#   enrich-5: Extract references from PDFs
#   enrich-7: Extract abstracts from PDFs
#
# GROBID is started automatically if not already running (see
# scripts/lib/ensure_grobid.sh) and stopped on exit if this script started it.

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
            echo "Step 3.5: Extract references and abstracts from PDFs using GROBID"
            echo ""
            echo "This is the last-resort fallback for papers where"
            echo "API-based enrichment (OpenAlex, CrossRef) failed."
            echo ""
            echo "GROBID is auto-started if not already running, and stopped"
            echo "on exit if this script started it."
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

# Ensure GROBID is up — auto-starts a container if needed and stops it on exit
# only if we started it (a pre-existing GROBID is left running). Dry-run only
# counts, so skip the spin-up.
source "$SCRIPT_DIR/../lib/ensure_grobid.sh"
if [ "$DRY_RUN" != true ]; then
    ensure_grobid
fi

CMD="uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --parallel $PARALLEL --batch-size $BATCH_SIZE --grobid-url $GROBID_URL"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[PDF/GROBID] Reference extraction complete."
echo ""

# Also extract abstracts from PDFs (enrich-7)
echo "[PDF/GROBID] Extracting abstracts from PDFs..."

CMD="uv run python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid --parallel $PARALLEL --batch-size $BATCH_SIZE --grobid-url $GROBID_URL"

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

if [ "$LIMIT" -gt 0 ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo "[PDF/GROBID] Complete."
