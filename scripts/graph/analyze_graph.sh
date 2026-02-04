#!/bin/bash
# Analyze Citation Graph
#
# Computes graph metrics and stores them in Qdrant:
#   - PageRank: paper importance by citation flow
#   - HITS: hub scores (surveys) and authority scores (foundational)
#   - Communities: research topic clusters
#
# Memory: ~2-3 GB for 150K nodes (loads full graph for analysis)
# Time: ~10-15 min for 150K nodes
#
# NOTE: Requires scipy for PageRank/HITS. Install with:
#   uv pip install scipy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
COMPUTE_PAGERANK=${COMPUTE_PAGERANK:-true}
COMPUTE_HITS=${COMPUTE_HITS:-false}
COMPUTE_COMMUNITIES=${COMPUTE_COMMUNITIES:-true}
STORE_METRICS=${STORE_METRICS:-true}
TOP_N=${TOP_N:-50}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --all)
            COMPUTE_PAGERANK=true
            COMPUTE_HITS=true
            COMPUTE_COMMUNITIES=true
            shift
            ;;
        --pagerank)
            COMPUTE_PAGERANK=true
            shift
            ;;
        --no-pagerank)
            COMPUTE_PAGERANK=false
            shift
            ;;
        --hits)
            COMPUTE_HITS=true
            shift
            ;;
        --no-hits)
            COMPUTE_HITS=false
            shift
            ;;
        --communities)
            COMPUTE_COMMUNITIES=true
            shift
            ;;
        --no-communities)
            COMPUTE_COMMUNITIES=false
            shift
            ;;
        --store)
            STORE_METRICS=true
            shift
            ;;
        --no-store)
            STORE_METRICS=false
            shift
            ;;
        --top-n)
            TOP_N="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Analyze citation graph and compute metrics"
            echo ""
            echo "Options:"
            echo "  --all               Compute all metrics (PageRank, HITS, communities)"
            echo "  --pagerank          Compute PageRank (default: on)"
            echo "  --no-pagerank       Skip PageRank"
            echo "  --hits              Compute HITS hub/authority scores"
            echo "  --no-hits           Skip HITS (default: off)"
            echo "  --communities       Compute community detection (default: on)"
            echo "  --no-communities    Skip community detection"
            echo "  --store             Store metrics to Qdrant (default: on)"
            echo "  --no-store          Don't store metrics"
            echo "  --top-n N           Show top N papers per metric (default: 50)"
            echo "  --help              Show this help"
            echo ""
            echo "Memory requirement: ~2-3 GB for 150K nodes"
            echo "Requires: scipy (uv pip install scipy)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Analyze Citation Graph"
echo "=========================================="
echo "Compute PageRank: $COMPUTE_PAGERANK"
echo "Compute HITS: $COMPUTE_HITS"
echo "Compute communities: $COMPUTE_COMMUNITIES"
echo "Store metrics: $STORE_METRICS"
echo "Top N: $TOP_N"
echo "=========================================="
echo ""

# Build command
CMD="uv run python -m src.cli.core_collect analyze-citation-graph"

if [ "$COMPUTE_PAGERANK" = true ]; then
    CMD="$CMD --compute-pagerank"
fi

if [ "$COMPUTE_HITS" = true ]; then
    CMD="$CMD --compute-hits"
fi

if [ "$COMPUTE_COMMUNITIES" = true ]; then
    CMD="$CMD --compute-communities"
fi

if [ "$STORE_METRICS" = true ]; then
    CMD="$CMD --store"
fi

CMD="$CMD --top-n $TOP_N"

echo "Running: $CMD"
echo ""

$CMD

echo ""
echo "=========================================="
echo "Analysis Complete!"
echo "=========================================="
if [ "$STORE_METRICS" = true ]; then
    echo ""
    echo "Metrics stored in Qdrant. You can now query papers by:"
    echo "  - pagerank: Paper importance score"
    echo "  - hub_score: Survey/review paper score (if HITS computed)"
    echo "  - authority_score: Foundational paper score (if HITS computed)"
    echo "  - community_id: Research topic cluster"
fi
