#!/bin/bash
# Full pipeline script (Orchestrator)
# Runs all 5 stages in sequence:
#   Stage 1: Collection    - Collect papers from all sources
#   Stage 2: Deduplication - Remove duplicate papers
#   Stage 3: Enrichment    - Enrich with citations and abstracts
#   Stage 4: Resolution    - Resolve references to internal IDs
#   Stage 5: Graph         - Build citation graph (cited_by)

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
SKIP_GRAPH=${SKIP_GRAPH:-false}
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
        --skip-graph)
            SKIP_GRAPH=true
            shift
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Run the full 5-stage pipeline"
            echo ""
            echo "Stages:"
            echo "  1. Collection    - Collect papers from all sources"
            echo "  2. Deduplication - Remove duplicate papers"
            echo "  3. Enrichment    - Enrich with citations and abstracts"
            echo "  4. Resolution    - Resolve references to internal IDs"
            echo "  5. Graph         - Build citation graph (cited_by)"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR     Start year (default: 2020)"
            echo "  --include-workshops   Include ACL workshop papers"
            echo "  --skip-collection     Skip Stage 1: Collection"
            echo "  --skip-dedup          Skip Stage 2: Deduplication"
            echo "  --skip-enrichment     Skip Stage 3: Enrichment"
            echo "  --skip-resolution     Skip Stage 4: Resolution"
            echo "  --skip-graph          Skip Stage 5: Graph"
            echo "  --parallel N          Concurrent requests (default: 10)"
            echo "  --help                Show this help message"
            echo ""
            echo "Examples:"
            echo "  # Full pipeline"
            echo "  $0 --since-year 2020"
            echo ""
            echo "  # Skip collection (post-processing only)"
            echo "  $0 --skip-collection"
            echo ""
            echo "  # Only enrichment and resolution"
            echo "  $0 --skip-collection --skip-dedup --skip-graph"
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
echo "Skip Graph: $SKIP_GRAPH"
echo "Parallel: $PARALLEL"
echo "=========================================="
echo ""

# Stage 1: Collection
if [ "$SKIP_COLLECTION" = false ]; then
    echo "============ [1/5] COLLECTION ============"
    CMD="$SCRIPT_DIR/crawler/run_full_collection.sh --since-year $SINCE_YEAR"
    if [ "$INCLUDE_WORKSHOPS" = true ]; then
        CMD="$CMD --include-workshops"
    fi
    $CMD
    echo ""
else
    echo "============ [1/5] COLLECTION (SKIPPED) ============"
    echo ""
fi

# Stage 2: Deduplication
if [ "$SKIP_DEDUP" = false ]; then
    echo "============ [2/5] DEDUPLICATION ============"
    "$SCRIPT_DIR/maintenance/run_deduplication.sh" --apply
    echo ""
else
    echo "============ [2/5] DEDUPLICATION (SKIPPED) ============"
    echo ""
fi

# Stage 3: Enrichment
if [ "$SKIP_ENRICHMENT" = false ]; then
    echo "============ [3/5] ENRICHMENT ============"
    "$SCRIPT_DIR/enrichment/run_enrichment.sh" --parallel "$PARALLEL"
    echo ""
else
    echo "============ [3/5] ENRICHMENT (SKIPPED) ============"
    echo ""
fi

# Stage 4: Resolution
if [ "$SKIP_RESOLUTION" = false ]; then
    echo "============ [4/5] RESOLUTION ============"
    "$SCRIPT_DIR/resolution/run_resolution.sh"
    echo ""
else
    echo "============ [4/5] RESOLUTION (SKIPPED) ============"
    echo ""
fi

# Stage 5: Graph
if [ "$SKIP_GRAPH" = false ]; then
    echo "============ [5/5] GRAPH ============"
    "$SCRIPT_DIR/graph/build_cited_by.sh"
    echo ""
else
    echo "============ [5/5] GRAPH (SKIPPED) ============"
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
