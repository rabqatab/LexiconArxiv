#!/bin/bash
# Count papers available from OpenAlex (dry run)
# Use this before starting a full collection to estimate time

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
TO_YEAR=${TO_YEAR:-""}

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
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR  Start year (default: 2020)"
            echo "  --to-year YEAR     End year (optional)"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Counting papers from OpenAlex..."
echo ""

CMD="uv run python -m src.cli.core_collect collect --all --count-only --since-year $SINCE_YEAR"

if [ -n "$TO_YEAR" ]; then
    CMD="$CMD --to-year $TO_YEAR"
fi

$CMD
