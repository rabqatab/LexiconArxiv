#!/bin/bash
# =============================================================================
# Incremental Pipeline for LexiconArxiv
# =============================================================================
# Runs the full incremental update pipeline:
# 1. Collect new papers from all sources
# 2. Enrich with abstracts and citations
# 3. Extract keywords for BM25 search
# 4. Resolve references and create stubs
# 5. Enrich stub papers
# 6. Rebuild citation graph
#
# Usage:
#   ./scripts/run_incremental_pipeline.sh              # Daily (1 day)
#   ./scripts/run_incremental_pipeline.sh --days 7     # Weekly
#   ./scripts/run_incremental_pipeline.sh --days 30    # Monthly
#   ./scripts/run_incremental_pipeline.sh --days 90    # Quarterly
#
# Crontab examples:
#   # Daily at 2 AM
#   0 2 * * * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh >> logs/cron.log 2>&1
#
#   # Quarterly (1st of Jan, Apr, Jul, Oct at 2 AM)
#   0 2 1 1,4,7,10 * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 >> logs/cron.log 2>&1
# =============================================================================

set -e  # Exit on error

# Parse arguments
DAYS=1
SKIP_GRAPH=false
DRY_RUN=false
PARALLEL=5

while [[ $# -gt 0 ]]; do
    case $1 in
        --days|-d)
            DAYS="$2"
            shift 2
            ;;
        --skip-graph)
            SKIP_GRAPH=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --parallel|-p)
            PARALLEL="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --days, -d N      Days to look back (default: 1)"
            echo "  --parallel, -p N  Concurrent API requests (default: 5)"
            echo "  --skip-graph      Skip citation graph rebuild"
            echo "  --dry-run         Show what would be done without executing"
            echo "  --help, -h        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Ensure logs directory exists
mkdir -p logs

# Timestamp for logging
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "=============================================="
echo "Incremental Pipeline Started: $TIMESTAMP"
echo "Days back: $DAYS"
echo "Parallel requests: $PARALLEL"
echo "Skip graph: $SKIP_GRAPH"
echo "=============================================="

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would execute the following steps:"
    echo "  1. collect-incremental --days $DAYS"
    echo "  2. enrich-abstracts --parallel $PARALLEL"
    echo "  3. enrich-s2 --parallel $PARALLEL"
    echo "  4. enrich-crossref --parallel $PARALLEL"
    echo "  5. extract-keywords"
    echo "  6. resolve-refs --create-stubs"
    echo "  7. enrich-stubs --parallel $PARALLEL"
    if [ "$SKIP_GRAPH" = false ]; then
        echo "  8. build-cited-by --incremental"
    fi
    exit 0
fi

# Track timing
START_TIME=$(date +%s)

# Step 1: Collect new papers
echo ""
echo "[Step 1/7] Collecting new papers (last $DAYS days)..."
uv run python -m src.cli.core_collect collect-incremental --days "$DAYS"

# Step 2: Enrich abstracts
echo ""
echo "[Step 2/7] Enriching abstracts..."
uv run python -m src.cli.core_collect enrich-abstracts --parallel "$PARALLEL"

# Step 3: Enrich citations via Semantic Scholar
echo ""
echo "[Step 3/7] Enriching citations (Semantic Scholar)..."
uv run python -m src.cli.core_collect enrich-s2 --parallel "$PARALLEL"

# Step 4: Enrich citations via CrossRef (for papers S2 missed)
echo ""
echo "[Step 4/7] Enriching citations (CrossRef)..."
uv run python -m src.cli.core_collect enrich-crossref --parallel "$PARALLEL"

# Step 5: Extract keywords
echo ""
echo "[Step 5/7] Extracting keywords..."
uv run python -m src.cli.core_collect extract-keywords

# Step 6: Resolve references and create stubs
echo ""
echo "[Step 6/7] Resolving references..."
uv run python -m src.cli.core_collect resolve-refs --create-stubs

# Step 7: Enrich stub papers
echo ""
echo "[Step 7/7] Enriching stub papers..."
uv run python -m src.cli.core_collect enrich-stubs --parallel "$PARALLEL"

# Step 8: Incrementally update cited_by index (optional)
if [ "$SKIP_GRAPH" = false ]; then
    echo ""
    echo "[Step 8/8] Updating cited_by index (incremental)..."
    uv run python -m src.cli.core_collect build-cited-by --incremental
fi

# Done
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo ""
echo "=============================================="
echo "Incremental Pipeline Completed!"
echo "Duration: ${MINUTES}m ${SECONDS}s"
echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# Show final stats
echo ""
uv run python -m src.cli.core_collect status
