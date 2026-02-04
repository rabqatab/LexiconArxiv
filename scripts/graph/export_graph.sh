#!/bin/bash
# Export Citation Graph
#
# For large graphs (150K+ nodes, 10M+ edges):
#   - Use --streaming (default) for CSV export with low memory
#   - Streaming writes directly to files without loading full graph
#
# For smaller graphs or other formats:
#   - Use --no-streaming with --format json/graphml/gexf
#   - Requires ~2-3 GB RAM for 150K nodes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
EXPORT_DIR=${EXPORT_DIR:-"data/graph"}
EXPORT_FORMAT=${EXPORT_FORMAT:-"csv"}
STREAMING=${STREAMING:-true}
VENUE_FILTER=""
YEAR_START=""
YEAR_END=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --output-dir)
            EXPORT_DIR="$2"
            shift 2
            ;;
        --format)
            EXPORT_FORMAT="$2"
            shift 2
            ;;
        --streaming)
            STREAMING=true
            shift
            ;;
        --no-streaming)
            STREAMING=false
            shift
            ;;
        --venue)
            VENUE_FILTER="$VENUE_FILTER -v $2"
            shift 2
            ;;
        --year-start)
            YEAR_START="$2"
            shift 2
            ;;
        --year-end)
            YEAR_END="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Export citation graph to files"
            echo ""
            echo "Options:"
            echo "  --output-dir DIR    Output directory (default: data/graph)"
            echo "  --format FMT        Export format: csv, json, graphml, gexf (default: csv)"
            echo "  --streaming         Use streaming export (low memory, CSV only, default)"
            echo "  --no-streaming      Use in-memory export (more formats, more RAM)"
            echo "  --venue VENUE       Filter by venue (can repeat: --venue ACL --venue EMNLP)"
            echo "  --year-start YEAR   Filter papers from this year"
            echo "  --year-end YEAR     Filter papers until this year"
            echo "  --help              Show this help"
            echo ""
            echo "Examples:"
            echo "  # Large graph: streaming CSV (recommended)"
            echo "  $0 --streaming --output-dir /tmp/graph"
            echo ""
            echo "  # For Gephi: GraphML (requires more RAM)"
            echo "  $0 --no-streaming --format graphml --output-dir /tmp/graph"
            echo ""
            echo "  # Filter by venue"
            echo "  $0 --venue ACL --venue EMNLP --output-dir /tmp/nlp_graph"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Export Citation Graph"
echo "=========================================="
echo "Output dir: $EXPORT_DIR"
echo "Format: $EXPORT_FORMAT"
echo "Streaming: $STREAMING"
echo "Venue filter: ${VENUE_FILTER:-none}"
echo "Year range: ${YEAR_START:-any} - ${YEAR_END:-any}"
echo "=========================================="
echo ""

# Show stats first
echo "Current graph statistics:"
uv run python -m src.cli.core_collect citation-graph-stats
echo ""

# Create output directory
mkdir -p "$EXPORT_DIR"

# Build export command
if [ "$STREAMING" = true ]; then
    if [ -n "$VENUE_FILTER" ] || [ -n "$YEAR_START" ] || [ -n "$YEAR_END" ]; then
        echo "Warning: Filters not supported with --streaming. Exporting full graph."
    fi

    echo "Exporting with streaming (low memory)..."
    uv run python -m src.cli.core_collect build-citation-graph \
        --output "$EXPORT_DIR" \
        --streaming
else
    OUTPUT_FILE="$EXPORT_DIR/citation_graph.$EXPORT_FORMAT"

    CMD="uv run python -m src.cli.core_collect build-citation-graph"
    CMD="$CMD --output $OUTPUT_FILE"
    CMD="$CMD --format $EXPORT_FORMAT"

    if [ -n "$VENUE_FILTER" ]; then
        CMD="$CMD $VENUE_FILTER"
    fi

    if [ -n "$YEAR_START" ]; then
        CMD="$CMD --year-start $YEAR_START"
    fi

    if [ -n "$YEAR_END" ]; then
        CMD="$CMD --year-end $YEAR_END"
    fi

    echo "Exporting with in-memory graph..."
    echo "Running: $CMD"
    $CMD
fi

echo ""
echo "=========================================="
echo "Export Complete!"
echo "=========================================="
echo ""
echo "Output files:"
ls -lh "$EXPORT_DIR"/*.csv "$EXPORT_DIR"/*.json "$EXPORT_DIR"/*.graphml "$EXPORT_DIR"/*.gexf 2>/dev/null || true
