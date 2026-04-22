#!/bin/bash
# Step 1.1: Collect papers from OpenAlex
# Primary source for ML/AI venues (NeurIPS, ICML, ICLR, AAAI, IJCAI, etc.)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
TO_YEAR=${TO_YEAR:-""}
COUNT_ONLY=${COUNT_ONLY:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --to-year)
            TO_YEAR="$2"
            shift 2
            ;;
        --count-only)
            COUNT_ONLY=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Collect papers from OpenAlex (ML/AI venues)"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR  Start year (default: 2020)"
            echo "  --to-year YEAR     End year (optional)"
            echo "  --count-only       Only count papers, don't collect"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[OpenAlex] Collecting papers since $SINCE_YEAR..."

CMD="uv run python -m src.cli.core_collect collect --all --since-year $SINCE_YEAR"

if [ -n "$TO_YEAR" ]; then
    CMD="$CMD --to-year $TO_YEAR"
fi

if [ "$COUNT_ONLY" = true ]; then
    CMD="$CMD --count-only"
fi

$CMD

echo "[OpenAlex] Collection complete."
