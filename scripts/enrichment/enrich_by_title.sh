#!/bin/bash
# Step 3.3: Enrich papers by title lookup
# For papers WITHOUT DOIs - searches OpenAlex by title

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-5}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich papers WITHOUT DOIs by title search"
            echo ""
            echo "Options:"
            echo "  --parallel N  Concurrent requests (default: 5)"
            echo "  --help        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "[Title Lookup] Enriching citations by title..."

uv run python -m src.cli.core_collect enrich-citations-by-title --parallel "$PARALLEL"

echo "[Title Lookup] Enrichment complete."
