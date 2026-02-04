#!/bin/bash
# Citation Graph Pipeline
# Builds citation graph, computes metrics, and prepares for GraphRAG
#
# Prerequisites:
#   - resolve-refs has been run (papers have resolved_references)
#   - Sufficient memory for analysis (or use --streaming for export)
#
# For 150K+ nodes:
#   - cited_by build: ~5-10 min, low memory
#   - Analysis: ~2-3 GB RAM, ~10-15 min
#   - Streaming export: low memory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SKIP_CITED_BY=${SKIP_CITED_BY:-false}
SKIP_ANALYSIS=${SKIP_ANALYSIS:-false}
SKIP_EXPORT=${SKIP_EXPORT:-false}
COMPUTE_PAGERANK=${COMPUTE_PAGERANK:-true}
COMPUTE_COMMUNITIES=${COMPUTE_COMMUNITIES:-true}
STORE_METRICS=${STORE_METRICS:-true}
EXPORT_FORMAT=${EXPORT_FORMAT:-"csv"}
EXPORT_DIR=${EXPORT_DIR:-"data/graph"}
STREAMING=${STREAMING:-true}
TOP_N=${TOP_N:-50}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-cited-by)
            SKIP_CITED_BY=true
            shift
            ;;
        --skip-analysis)
            SKIP_ANALYSIS=true
            shift
            ;;
        --skip-export)
            SKIP_EXPORT=true
            shift
            ;;
        --no-pagerank)
            COMPUTE_PAGERANK=false
            shift
            ;;
        --no-communities)
            COMPUTE_COMMUNITIES=false
            shift
            ;;
        --no-store)
            STORE_METRICS=false
            shift
            ;;
        --export-format)
            EXPORT_FORMAT="$2"
            shift 2
            ;;
        --export-dir)
            EXPORT_DIR="$2"
            shift 2
            ;;
        --no-streaming)
            STREAMING=false
            shift
            ;;
        --top-n)
            TOP_N="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Citation Graph Pipeline - builds graph, computes metrics, exports"
            echo ""
            echo "Options:"
            echo "  --skip-cited-by     Skip building cited_by field"
            echo "  --skip-analysis     Skip graph analysis (PageRank, etc.)"
            echo "  --skip-export       Skip graph export"
            echo "  --no-pagerank       Don't compute PageRank"
            echo "  --no-communities    Don't detect communities"
            echo "  --no-store          Don't store metrics to Qdrant"
            echo "  --export-format FMT Export format: csv, json, graphml, gexf (default: csv)"
            echo "  --export-dir DIR    Export directory (default: data/graph)"
            echo "  --no-streaming      Use in-memory export (requires more RAM)"
            echo "  --top-n N           Show top N papers per metric (default: 50)"
            echo "  --help              Show this help"
            echo ""
            echo "For 150K+ nodes:"
            echo "  - Use --streaming (default) for low-memory CSV export"
            echo "  - Analysis requires ~2-3 GB RAM"
            echo "  - cited_by build is always low-memory"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Citation Graph Pipeline"
echo "=========================================="
echo "Skip cited_by: $SKIP_CITED_BY"
echo "Skip analysis: $SKIP_ANALYSIS"
echo "Skip export: $SKIP_EXPORT"
echo "Compute PageRank: $COMPUTE_PAGERANK"
echo "Compute communities: $COMPUTE_COMMUNITIES"
echo "Store metrics: $STORE_METRICS"
echo "Export format: $EXPORT_FORMAT"
echo "Export dir: $EXPORT_DIR"
echo "Streaming: $STREAMING"
echo "=========================================="
echo ""

# Step 0: Show current stats
echo "============ [0/3] CURRENT STATUS ============"
uv run python -m src.cli.core_collect citation-graph-stats
echo ""

# Step 1: Build cited_by field (for GraphRAG)
if [ "$SKIP_CITED_BY" = false ]; then
    echo "============ [1/3] BUILD CITED_BY ============"
    echo "Building reverse citation index for GraphRAG..."
    echo "(This enables bidirectional citation traversal)"
    echo ""
    uv run python -m src.cli.core_collect build-cited-by
    echo ""
else
    echo "============ [1/3] BUILD CITED_BY (SKIPPED) ============"
    echo ""
fi

# Step 2: Graph Analysis
if [ "$SKIP_ANALYSIS" = false ]; then
    echo "============ [2/3] GRAPH ANALYSIS ============"

    ANALYSIS_ARGS=""

    if [ "$COMPUTE_PAGERANK" = true ]; then
        ANALYSIS_ARGS="$ANALYSIS_ARGS --compute-pagerank"
    fi

    if [ "$COMPUTE_COMMUNITIES" = true ]; then
        ANALYSIS_ARGS="$ANALYSIS_ARGS --compute-communities"
    fi

    if [ "$STORE_METRICS" = true ]; then
        ANALYSIS_ARGS="$ANALYSIS_ARGS --store"
    fi

    ANALYSIS_ARGS="$ANALYSIS_ARGS --top-n $TOP_N"

    if [ -n "$ANALYSIS_ARGS" ]; then
        echo "Running: uv run python -m src.cli.core_collect analyze-citation-graph $ANALYSIS_ARGS"
        uv run python -m src.cli.core_collect analyze-citation-graph $ANALYSIS_ARGS
    else
        echo "No analysis options selected, skipping."
    fi
    echo ""
else
    echo "============ [2/3] GRAPH ANALYSIS (SKIPPED) ============"
    echo ""
fi

# Step 3: Export Graph
if [ "$SKIP_EXPORT" = false ]; then
    echo "============ [3/3] GRAPH EXPORT ============"

    mkdir -p "$EXPORT_DIR"

    if [ "$STREAMING" = true ]; then
        echo "Using streaming export (low memory)..."
        echo "Output: $EXPORT_DIR/"
        uv run python -m src.cli.core_collect build-citation-graph \
            --output "$EXPORT_DIR" \
            --streaming
    else
        OUTPUT_FILE="$EXPORT_DIR/citation_graph.$EXPORT_FORMAT"
        echo "Using in-memory export..."
        echo "Output: $OUTPUT_FILE"
        uv run python -m src.cli.core_collect build-citation-graph \
            --output "$OUTPUT_FILE" \
            --format "$EXPORT_FORMAT"
    fi
    echo ""
else
    echo "============ [3/3] GRAPH EXPORT (SKIPPED) ============"
    echo ""
fi

echo "=========================================="
echo "Citation Graph Pipeline Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  - For GraphRAG: cited_by field is ready for bidirectional queries"
echo "  - For visualization: import CSV/GraphML into Gephi"
echo "  - For analysis: PageRank scores stored in Qdrant (query by pagerank field)"
