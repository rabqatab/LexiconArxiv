#!/bin/bash
# Step 1.4: Collect papers from OpenReview
# ML conference papers (ICLR, NeurIPS, ICML)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Collect papers from OpenReview (ICLR, NeurIPS, ICML)"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR  Start year (default: 2020)"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[OpenReview] Collecting papers since $SINCE_YEAR..."

uv run python -m src.cli.core_collect collect-openreview --all --since-year $SINCE_YEAR

echo "[OpenReview] Collection complete."
