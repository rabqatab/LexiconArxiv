#!/bin/bash
# Collect papers from ACM venues via DBLP
# ACM conferences (KDD, SIGIR, WWW, etc.)

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
            echo "Collect papers from ACM venues via DBLP"
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

echo "[ACM] Collecting papers since $SINCE_YEAR..."

uv run python -m src.cli.core_collect collect-dblp --all --acm-only --since-year $SINCE_YEAR

echo "[ACM] Collection complete."
