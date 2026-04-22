#!/bin/bash
# Step 1.2: Collect papers from ACL Anthology
# Primary source for NLP venues (ACL, EMNLP, NAACL, EACL, COLING, etc.)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
INCLUDE_WORKSHOPS=${INCLUDE_WORKSHOPS:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --include-workshops)
            INCLUDE_WORKSHOPS=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Collect papers from ACL Anthology (NLP venues)"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR    Start year (default: 2020)"
            echo "  --include-workshops  Include workshop papers"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[ACL Anthology] Collecting papers since $SINCE_YEAR..."

CMD="uv run python -m src.cli.core_collect collect-acl --all --since-year $SINCE_YEAR"

if [ "$INCLUDE_WORKSHOPS" = true ]; then
    CMD="$CMD --include-workshops"
fi

$CMD

echo "[ACL Anthology] Collection complete."
