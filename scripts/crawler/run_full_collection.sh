#!/bin/bash
# Full corpus collection script
# Run this once for initial collection

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
SKIP_OPENALEX=${SKIP_OPENALEX:-false}
SKIP_ACL=${SKIP_ACL:-false}
SKIP_DBLP=${SKIP_DBLP:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --skip-openalex)
            SKIP_OPENALEX=true
            shift
            ;;
        --skip-acl)
            SKIP_ACL=true
            shift
            ;;
        --skip-dblp)
            SKIP_DBLP=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR    Start year (default: 2020)"
            echo "  --skip-openalex      Skip OpenAlex collection"
            echo "  --skip-acl           Skip ACL Anthology collection"
            echo "  --skip-dblp          Skip DBLP collection"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Full Corpus Collection"
echo "=========================================="
echo "Start Year: $SINCE_YEAR"
echo "Skip OpenAlex: $SKIP_OPENALEX"
echo "Skip ACL: $SKIP_ACL"
echo "Skip DBLP: $SKIP_DBLP"
echo "=========================================="
echo ""

# Build command
CMD="uv run python -m src.cli.core_collect collect-all-sources --since-year $SINCE_YEAR"

if [ "$SKIP_OPENALEX" = true ]; then
    CMD="$CMD --skip-openalex"
fi

if [ "$SKIP_ACL" = true ]; then
    CMD="$CMD --skip-acl"
fi

if [ "$SKIP_DBLP" = true ]; then
    CMD="$CMD --skip-dblp"
fi

echo "Running: $CMD"
echo ""

# Run collection
$CMD

echo ""
echo "=========================================="
echo "Collection complete!"
echo "=========================================="
