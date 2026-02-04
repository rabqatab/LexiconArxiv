#!/bin/bash
# Paper enrichment script
# 3-step enrichment: DOI lookup -> Title lookup -> PDF extraction

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-50}
SKIP_CITATIONS=${SKIP_CITATIONS:-false}
SKIP_TITLE=${SKIP_TITLE:-false}
SKIP_PDF=${SKIP_PDF:-false}
SKIP_ABSTRACTS=${SKIP_ABSTRACTS:-false}

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
        --skip-citations)
            SKIP_CITATIONS=true
            shift
            ;;
        --skip-title)
            SKIP_TITLE=true
            shift
            ;;
        --skip-pdf)
            SKIP_PDF=true
            shift
            ;;
        --skip-abstracts)
            SKIP_ABSTRACTS=true
            shift
            ;;
        --citations-only)
            SKIP_ABSTRACTS=true
            shift
            ;;
        --abstracts-only)
            SKIP_CITATIONS=true
            SKIP_TITLE=true
            SKIP_PDF=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --parallel N       Concurrent requests (default: 10)"
            echo "  --batch-size N     Batch size for updates (default: 50)"
            echo "  --skip-citations   Skip DOI-based citation enrichment"
            echo "  --skip-title       Skip title-based citation enrichment"
            echo "  --skip-pdf         Skip PDF reference extraction"
            echo "  --skip-abstracts   Skip abstract enrichment"
            echo "  --citations-only   Only enrich citations (skip abstracts)"
            echo "  --abstracts-only   Only enrich abstracts"
            echo "  --help             Show this help message"
            echo ""
            echo "Enrichment Steps:"
            echo "  1. DOI lookup     - Papers WITH DOIs via OpenAlex"
            echo "  2. Title lookup   - Papers WITHOUT DOIs via OpenAlex title search"
            echo "  3. PDF extraction - Papers still missing refs via GROBID"
            echo "  4. Abstracts      - Fill missing abstracts via OpenAlex"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Paper Enrichment"
echo "=========================================="
echo "Parallel: $PARALLEL"
echo "Batch Size: $BATCH_SIZE"
echo "Skip Citations (DOI): $SKIP_CITATIONS"
echo "Skip Title Lookup: $SKIP_TITLE"
echo "Skip PDF Extraction: $SKIP_PDF"
echo "Skip Abstracts: $SKIP_ABSTRACTS"
echo "=========================================="
echo ""

# Step 1: DOI-based citation enrichment
if [ "$SKIP_CITATIONS" = false ]; then
    echo "[1/4] Enriching citations (papers WITH DOIs)..."
    uv run python -m src.cli.core_collect enrich-citations --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"
    echo ""
else
    echo "[1/4] DOI-based enrichment (SKIPPED)"
    echo ""
fi

# Step 2: Title-based citation enrichment
if [ "$SKIP_TITLE" = false ]; then
    echo "[2/4] Enriching citations by title (papers WITHOUT DOIs)..."
    uv run python -m src.cli.core_collect enrich-citations-by-title --parallel 5
    echo ""
else
    echo "[2/4] Title-based enrichment (SKIPPED)"
    echo ""
fi

# Step 3: PDF reference extraction
if [ "$SKIP_PDF" = false ]; then
    if curl -s http://localhost:8070/api/isalive > /dev/null 2>&1; then
        echo "[3/4] Extracting references from PDFs (GROBID available)..."
        uv run python -m src.cli.core_collect extract-pdf-refs
        echo ""
    else
        echo "[3/4] PDF extraction (SKIPPED - GROBID not running)"
        echo "    To enable: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
        echo ""
    fi
else
    echo "[3/4] PDF extraction (SKIPPED)"
    echo ""
fi

# Step 4: Abstract enrichment
if [ "$SKIP_ABSTRACTS" = false ]; then
    echo "[4/4] Enriching abstracts..."
    uv run python -m src.cli.core_collect enrich-abstracts --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"
    echo ""
else
    echo "[4/4] Abstract enrichment (SKIPPED)"
    echo ""
fi

echo "=========================================="
echo "Enrichment complete!"
echo "=========================================="

# Show data quality stats
echo ""
echo "Data Quality Summary:"
uv run python -m src.cli.core_collect status
