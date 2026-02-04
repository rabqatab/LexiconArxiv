#!/bin/bash
# Full pipeline script
# Runs: Collection -> Deduplication -> Enrichment -> Resolution

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
INCLUDE_WORKSHOPS=${INCLUDE_WORKSHOPS:-false}
SKIP_COLLECTION=${SKIP_COLLECTION:-false}
SKIP_DEDUP=${SKIP_DEDUP:-false}
SKIP_ENRICHMENT=${SKIP_ENRICHMENT:-false}
SKIP_RESOLUTION=${SKIP_RESOLUTION:-false}
PARALLEL=${PARALLEL:-10}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --include-workshops)
            INCLUDE_WORKSHOPS=true
            shift
            ;;
        --skip-collection)
            SKIP_COLLECTION=true
            shift
            ;;
        --skip-dedup)
            SKIP_DEDUP=true
            shift
            ;;
        --skip-enrichment)
            SKIP_ENRICHMENT=true
            shift
            ;;
        --skip-resolution)
            SKIP_RESOLUTION=true
            shift
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR     Start year (default: 2020)"
            echo "  --include-workshops   Include ACL workshop papers"
            echo "  --skip-collection     Skip data collection step"
            echo "  --skip-dedup          Skip deduplication step"
            echo "  --skip-enrichment     Skip enrichment step"
            echo "  --skip-resolution     Skip resolution step"
            echo "  --parallel N          Concurrent requests (default: 10)"
            echo "  --help                Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Full Pipeline"
echo "=========================================="
echo "Since Year: $SINCE_YEAR"
echo "Include Workshops: $INCLUDE_WORKSHOPS"
echo "Skip Collection: $SKIP_COLLECTION"
echo "Skip Dedup: $SKIP_DEDUP"
echo "Skip Enrichment: $SKIP_ENRICHMENT"
echo "Skip Resolution: $SKIP_RESOLUTION"
echo "Parallel: $PARALLEL"
echo "=========================================="
echo ""

# Step 1: Collection
if [ "$SKIP_COLLECTION" = false ]; then
    echo "============ [1/4] COLLECTION ============"
    CMD="uv run python -m src.cli.core_collect collect-all-sources --since-year $SINCE_YEAR"
    if [ "$INCLUDE_WORKSHOPS" = true ]; then
        CMD="$CMD --include-workshops"
    fi
    echo "Running: $CMD"
    $CMD
    echo ""
else
    echo "============ [1/4] COLLECTION (SKIPPED) ============"
    echo ""
fi

# Step 2: Deduplication
if [ "$SKIP_DEDUP" = false ]; then
    echo "============ [2/4] DEDUPLICATION ============"
    uv run python -m src.cli.core_collect deduplicate
    echo ""
else
    echo "============ [2/4] DEDUPLICATION (SKIPPED) ============"
    echo ""
fi

# Step 3: Enrichment
if [ "$SKIP_ENRICHMENT" = false ]; then
    echo "============ [3/4] ENRICHMENT ============"

    # 3a. Enrich papers WITH DOIs via OpenAlex
    echo "[3a] Enriching citations (papers with DOIs)..."
    uv run python -m src.cli.core_collect enrich-citations --parallel "$PARALLEL"

    # 3b. Enrich papers WITHOUT DOIs via title search
    echo "[3b] Enriching citations by title (papers without DOIs)..."
    uv run python -m src.cli.core_collect enrich-citations-by-title --parallel 5

    # 3c. Extract refs from PDFs (if GROBID is running)
    if curl -s http://localhost:8070/api/isalive > /dev/null 2>&1; then
        echo "[3c] Extracting references from PDFs (GROBID available)..."
        uv run python -m src.cli.core_collect extract-pdf-refs
    else
        echo "[3c] GROBID not running - skipping PDF extraction"
        echo "    To enable: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
    fi

    # 3d. Enrich abstracts
    echo "[3d] Enriching abstracts..."
    uv run python -m src.cli.core_collect enrich-abstracts --parallel "$PARALLEL"
    echo ""
else
    echo "============ [3/4] ENRICHMENT (SKIPPED) ============"
    echo ""
fi

# Step 4: Reference Resolution
if [ "$SKIP_RESOLUTION" = false ]; then
    echo "============ [4/4] RESOLUTION ============"
    uv run python -m src.cli.core_collect resolve-refs
    echo ""
else
    echo "============ [4/4] RESOLUTION (SKIPPED) ============"
    echo ""
fi

echo "=========================================="
echo "Pipeline complete!"
echo "=========================================="
echo ""

# Final status
echo "Final Status:"
uv run python -m src.cli.core_collect status
echo ""
uv run python -m src.cli.core_collect ref-stats
