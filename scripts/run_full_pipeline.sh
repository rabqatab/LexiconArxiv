#!/bin/bash
# Full pipeline script (Orchestrator)
# Runs all 7 stages in sequence:
#   Stage 1: Collection    - Collect papers from all sources
#   Stage 2: Deduplication - Remove duplicate papers
#   Stage 3: Enrichment    - Enrich with citations and abstracts
#   Stage 4: Resolution    - Resolve references to internal IDs
#   Stage 5: Graph         - Build citation graph (cited_by)
#   Stage 6: Keywords      - Extract keywords and acronyms for BM25 search
#   Stage 7: Labeling      - Label abstract sentences with rhetorical roles

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
SKIP_KEYWORDS=${SKIP_KEYWORDS:-false}
SKIP_LABELING=${SKIP_LABELING:-false}
SKIP_SNAPSHOT=${SKIP_SNAPSHOT:-false}
PARALLEL=${PARALLEL:-10}
LOG_FILE=${LOG_FILE:-""}

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
        --skip-keywords)
            SKIP_KEYWORDS=true
            shift
            ;;
        --skip-labeling)
            SKIP_LABELING=true
            shift
            ;;
        --skip-snapshot)
            SKIP_SNAPSHOT=true
            shift
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --log)
            LOG_FILE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Run the full 7-stage pipeline"
            echo ""
            echo "Stages:"
            echo "  1. Collection    - Collect papers from all sources"
            echo "  2. Deduplication - Remove duplicate papers"
            echo "  3. Enrichment    - Enrich with citations and abstracts"
            echo "  4. Resolution    - Resolve references to internal IDs"
            echo "  5. Graph         - Build citation graph (cited_by)"
            echo "  6. Keywords      - Extract keywords and acronyms for BM25 search"
            echo "  7. Labeling      - Label abstract sentences with rhetorical roles"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR     Start year (default: 2020)"
            echo "  --include-workshops   Include ACL workshop papers"
            echo "  --skip-collection     Skip Stage 1: Collection"
            echo "  --skip-dedup          Skip Stage 2: Deduplication"
            echo "  --skip-enrichment     Skip Stage 3: Enrichment"
            echo "  --skip-resolution     Skip Stage 4: Resolution"
            echo "  --skip-graph          Skip Stage 5: Graph"
            echo "  --skip-keywords       Skip Stage 6: Keywords"
            echo "  --skip-labeling       Skip Stage 7: Labeling"
            echo "  --skip-snapshot       Skip pre-pipeline snapshot"
            echo "  --parallel N          Concurrent requests (default: 10)"
            echo "  --log FILE            Save output to log file (also prints to terminal)"
            echo "  --help                Show this help message"
            echo ""
            echo "Examples:"
            echo "  # Full pipeline"
            echo "  $0 --since-year 2020"
            echo ""
            echo "  # With logging"
            echo "  $0 --since-year 2017 --log logs/pipeline.log"
            echo ""
            echo "  # Skip collection (post-processing only)"
            echo "  $0 --skip-collection"
            echo ""
            echo "  # Only enrichment and resolution"
            echo "  $0 --skip-collection --skip-dedup --skip-graph --skip-keywords --skip-labeling"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Setup logging if --log is specified
if [ -n "$LOG_FILE" ]; then
    # Create log directory if needed
    LOG_DIR=$(dirname "$LOG_FILE")
    if [ "$LOG_DIR" != "." ] && [ ! -d "$LOG_DIR" ]; then
        mkdir -p "$LOG_DIR"
    fi
    # Redirect all output to both terminal and log file
    exec > >(tee -a "$LOG_FILE") 2>&1
    echo "Logging to: $LOG_FILE"
    echo ""
fi

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
echo "Skip Keywords: $SKIP_KEYWORDS"
echo "Skip Labeling: $SKIP_LABELING"
echo "Skip Snapshot: $SKIP_SNAPSHOT"
echo "Parallel: $PARALLEL"
echo "Log File: ${LOG_FILE:-"(none)"}"
echo "=========================================="
echo ""

# Pre-pipeline: Snapshot (safety net)
if [ "$SKIP_SNAPSHOT" = false ]; then
    echo "============ [PRE] SNAPSHOT ============"
    # Only snapshot if collection has data
    POINT_COUNT=$(curl -sf "${QDRANT_URL:-http://localhost:6333}/collections/${QDRANT_COLLECTION:-lexicon_arxiv}" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])" 2>/dev/null || echo "0")
    if [ "$POINT_COUNT" -gt 0 ] 2>/dev/null; then
        echo "Collection has ${POINT_COUNT} points. Creating snapshot..."
        "$SCRIPT_DIR/maintenance/qdrant_snapshot.sh"
    else
        echo "Collection is empty or Qdrant unreachable. Skipping snapshot."
    fi
    echo ""
else
    echo "============ [PRE] SNAPSHOT (SKIPPED) ============"
    echo ""
fi

# Stage 1: Collection
if [ "$SKIP_COLLECTION" = false ]; then
    echo "============ [1/7] COLLECTION ============"
    CMD="$SCRIPT_DIR/crawler/run_full_collection.sh --since-year $SINCE_YEAR"
    if [ "$INCLUDE_WORKSHOPS" = true ]; then
        CMD="$CMD --include-workshops"
    fi
    $CMD
    echo ""
else
    echo "============ [1/7] COLLECTION (SKIPPED) ============"
    echo ""
fi

# Stage 2: Deduplication
if [ "$SKIP_DEDUP" = false ]; then
    echo "============ [2/7] DEDUPLICATION ============"
    "$SCRIPT_DIR/maintenance/run_deduplication.sh" --apply
    echo ""
else
    echo "============ [2/7] DEDUPLICATION (SKIPPED) ============"
    echo ""
fi

# Stage 3: Enrichment
if [ "$SKIP_ENRICHMENT" = false ]; then
    echo "============ [3/7] ENRICHMENT ============"
    "$SCRIPT_DIR/enrichment/run_enrichment.sh" --parallel "$PARALLEL"
    echo ""
else
    echo "============ [3/7] ENRICHMENT (SKIPPED) ============"
    echo ""
fi

# Stage 4: Resolution
if [ "$SKIP_RESOLUTION" = false ]; then
    echo "============ [4/7] RESOLUTION ============"
    "$SCRIPT_DIR/resolution/run_resolution.sh"
    echo ""
else
    echo "============ [4/7] RESOLUTION (SKIPPED) ============"
    echo ""
fi

# Stage 5: Graph
if [ "$SKIP_GRAPH" = false ]; then
    echo "============ [5/7] GRAPH ============"
    "$SCRIPT_DIR/graph/build_cited_by.sh"
    echo ""
else
    echo "============ [5/7] GRAPH (SKIPPED) ============"
    echo ""
fi

# Stage 6: Keywords
if [ "$SKIP_KEYWORDS" = false ]; then
    echo "============ [6/7] KEYWORDS ============"
    "$SCRIPT_DIR/keywords/run_keywords.sh"
    echo ""
else
    echo "============ [6/7] KEYWORDS (SKIPPED) ============"
    echo ""
fi

# Stage 7: Labeling
if [ "$SKIP_LABELING" = false ]; then
    echo "============ [7/7] LABELING ============"
    "$SCRIPT_DIR/labeling/run_labeling.sh"
    echo ""
else
    echo "============ [7/7] LABELING (SKIPPED) ============"
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
echo ""
uv run python -m src.cli.core_collect keyword-stats
