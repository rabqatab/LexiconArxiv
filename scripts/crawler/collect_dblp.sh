#!/bin/bash
# Step 1.3: Collect papers from DBLP
# Supplementary source for IR/Legal venues (RecSys, ECIR, ICAIL, etc.)

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
            echo "Collect papers from DBLP (IR/Legal venues)"
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

echo "[DBLP] Collecting papers since $SINCE_YEAR..."

uv run python -m src.cli.core_collect collect-dblp --all --since-year $SINCE_YEAR

echo "[DBLP] Collection complete."
