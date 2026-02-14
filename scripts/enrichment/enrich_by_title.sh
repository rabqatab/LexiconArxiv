#!/bin/bash
# Step 3.3: Enrich papers by title lookup
# For papers WITHOUT DOIs - searches OpenAlex by title
#
# NOTE: OpenAlex search API has stricter rate limits than DOI lookup.
# Keep parallel low (1-2) to avoid 429 rate limit loops.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values - parallel auto-detected by Python code (3 for API key, 1 for email)
PARALLEL=""
RETRY_INCOMPLETE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --retry-incomplete)
            RETRY_INCOMPLETE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich papers WITHOUT DOIs by title search"
            echo ""
            echo "Options:"
            echo "  --parallel N          Concurrent requests (auto: 3 for API key, 1 for email)"
            echo "  --retry-incomplete    Re-process papers still missing data"
            echo "  --help                Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Title Lookup] Enriching citations by title..."

CMD="uv run python -m src.cli.core_collect enrich-citations-by-title"
[ -n "$PARALLEL" ] && CMD="$CMD --parallel $PARALLEL"
[ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
$CMD

echo "[Title Lookup] Enrichment complete."
