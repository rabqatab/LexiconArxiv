#!/bin/bash
# Paper enrichment script
# Adds citations and abstracts via OpenAlex API

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-50}
SKIP_CITATIONS=${SKIP_CITATIONS:-false}
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
        --citations-only)
            SKIP_ABSTRACTS=true
            shift
            ;;
        --abstracts-only)
            SKIP_CITATIONS=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --parallel N       Concurrent requests (default: 10)"
            echo "  --batch-size N     Batch size for updates (default: 50)"
            echo "  --citations-only   Only enrich citations"
            echo "  --abstracts-only   Only enrich abstracts"
            echo "  --help             Show this help message"
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
echo "Skip Citations: $SKIP_CITATIONS"
echo "Skip Abstracts: $SKIP_ABSTRACTS"
echo "=========================================="
echo ""

# Run citation enrichment
if [ "$SKIP_CITATIONS" = false ]; then
    echo "[1/2] Enriching citations..."
    uv run python -m src.cli.core_collect enrich-citations --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"
    echo ""
fi

# Run abstract enrichment
if [ "$SKIP_ABSTRACTS" = false ]; then
    echo "[2/2] Enriching abstracts..."
    uv run python -m src.cli.core_collect enrich-abstracts --parallel "$PARALLEL" --batch-size "$BATCH_SIZE"
    echo ""
fi

echo "=========================================="
echo "Enrichment complete!"
echo "=========================================="

# Show data quality stats
echo ""
echo "Data Quality Summary:"
uv run python -m src.cli.core_collect status
