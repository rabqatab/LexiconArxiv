#!/bin/bash
# =============================================================================
# Incremental Pipeline for LexiconArxiv
# =============================================================================
# Runs the full incremental update pipeline (10 stages):
#
# DATA COLLECTION & ENRICHMENT:
#   1. Collect new papers from all sources
#   2. Enrich with abstracts and citations
#   3. Extract keywords for BM25 search
#   4. Label abstracts with rhetorical roles
#   5. Resolve references and create stubs
#   6. Enrich stub papers
#
# GRAPH & SEARCH:
#   7. Rebuild citation graph (incremental cited_by)
#   8. Embed new papers (dense + section-level + BM25 vectors)
#
# WEEKLY MAINTENANCE (--weekly flag):
#   9. Recompute semantic similarity graph
#  10. Recompute graph analysis (PageRank, HITS, communities)
#
# Usage:
#   ./scripts/run_incremental_pipeline.sh              # Daily (1 day)
#   ./scripts/run_incremental_pipeline.sh --days 7     # Weekly
#   ./scripts/run_incremental_pipeline.sh --days 7 --weekly  # Weekly + maintenance
#   ./scripts/run_incremental_pipeline.sh --days 90 --weekly # Quarterly
#
# Crontab examples:
#   # Daily at 2 AM (collect + enrich + embed)
#   0 2 * * 1-6 cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh >> logs/cron.log 2>&1
#
#   # Weekly on Sunday at 2 AM (+ similarity + graph analysis)
#   0 2 * * 0 cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 7 --weekly >> logs/cron_weekly.log 2>&1
#
#   # Quarterly (1st of Jan, Apr, Jul, Oct — includes clustering)
#   0 2 1 1,4,7,10 * cd /path/to/LexiconArxiv && ./scripts/run_incremental_pipeline.sh --days 90 --weekly --cluster >> logs/cron_quarterly.log 2>&1
# =============================================================================

set -e  # Exit on error

# Pipeline status file for dashboard monitoring
STATUS_FILE="data/core/pipeline_status.json"
mkdir -p "$(dirname "$STATUS_FILE")"
trap 'echo "{\"status\": \"failed\", \"finished_at\": \"$(date -Iseconds)\", \"error\": \"Pipeline failed at step\", \"days\": $DAYS}" > "$STATUS_FILE"' ERR

# Parse arguments
DAYS=1
SKIP_GRAPH=false
SKIP_LABELING=false
SKIP_EMBED=false
WEEKLY=false
CLUSTER=false
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
        --skip-labeling)
            SKIP_LABELING=true
            shift
            ;;
        --skip-embed)
            SKIP_EMBED=true
            shift
            ;;
        --weekly)
            WEEKLY=true
            shift
            ;;
        --cluster)
            CLUSTER=true
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
            echo "  --skip-labeling   Skip abstract labeling"
            echo "  --skip-embed      Skip embedding (new papers won't be searchable)"
            echo "  --weekly          Run weekly maintenance (similarity + graph analysis)"
            echo "  --cluster         Recompute UMAP+HDBSCAN topic clusters (quarterly)"
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
echo "Skip labeling: $SKIP_LABELING"
echo "Skip embed: $SKIP_EMBED"
echo "Weekly maintenance: $WEEKLY"
echo "Cluster recompute: $CLUSTER"
echo "=============================================="

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would execute the following steps:"
    echo "  1. collect-incremental --days $DAYS"
    echo "  2. enrich-6-abstracts-by-doi-via-openalex --parallel $PARALLEL"
    echo "  3a. enrich-4-refs-by-doi-via-s2 --parallel $PARALLEL --recent-days $DAYS"
    if [ "$WEEKLY" = true ]; then
        echo "  3b. enrich-4-refs-by-doi-via-s2 --parallel $PARALLEL (backlog, background)"
    fi
    echo "  4. enrich-2-refs-by-doi-via-crossref --parallel $PARALLEL"
    echo "  5. extract-keywords"
    echo "  6. label-abstracts"
    echo "  7. resolve-refs --create-stubs"
    echo "  8. enrich-8-metadata-by-stub-via-openalex --parallel $PARALLEL"
    if [ "$SKIP_GRAPH" = false ]; then
        echo "  9. build-cited-by --incremental"
    fi
    if [ "$SKIP_EMBED" = false ]; then
        echo " 10. embed-papers (section-level + BM25 vectors)"
    fi
    if [ "$WEEKLY" = true ]; then
        echo " 11. compute-similarity (semantic similarity graph)"
        echo " 12. analyze-graph (PageRank, HITS, communities)"
    fi
    if [ "$CLUSTER" = true ]; then
        echo " 13. compute-topics (UMAP + HDBSCAN clustering)"
    fi
    exit 0
fi

# Track timing
START_TIME=$(date +%s)

# Step 1: Collect new papers
echo ""
echo "[Step 1] Collecting new papers (last $DAYS days)..."
uv run python -m src.cli.core_collect collect-incremental --days "$DAYS"

# Step 2: Enrich abstracts
echo ""
echo "[Step 2] Enriching abstracts..."
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel "$PARALLEL"

# Step 3a: Enrich citations via Semantic Scholar — NEW papers only (fast)
echo ""
echo "[Step 3a] Enriching citations (S2) — recent papers only..."
uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel "$PARALLEL" --recent-days "$DAYS"

# Step 3b: S2 backlog — run in background (slow, non-blocking)
S2_BACKLOG_PID=""
if [ "$WEEKLY" = true ]; then
    echo ""
    echo "[Step 3b] S2 backlog enrichment (background)..."
    uv run python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --parallel "$PARALLEL" &
    S2_BACKLOG_PID=$!
fi

# Step 4: Enrich citations via CrossRef (for papers S2 missed)
echo ""
echo "[Step 4] Enriching citations (CrossRef)..."
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel "$PARALLEL"

# Steps 5+6: Keywords & Labeling (parallel — independent fields)
KEYWORDS_PID=""
LABELING_PID=""

echo ""
echo "[Step 5] Extracting keywords..."
uv run python -m src.cli.core_collect extract-keywords &
KEYWORDS_PID=$!

if [ "$SKIP_LABELING" = false ]; then
    echo ""
    echo "[Step 6] Labeling abstracts..."
    uv run python -m src.cli.core_collect label-abstracts &
    LABELING_PID=$!
fi

# Wait for parallel steps to complete
FAILED=false
if ! wait "$KEYWORDS_PID"; then
    echo "[ERROR] Keyword extraction failed."
    FAILED=true
fi
if [ -n "$LABELING_PID" ]; then
    if ! wait "$LABELING_PID"; then
        echo "[ERROR] Abstract labeling failed."
        FAILED=true
    fi
fi
if [ "$FAILED" = true ]; then
    echo "One or more parallel steps failed."
    exit 1
fi

# Step 7: Resolve references and create stubs
echo ""
echo "[Step 7] Resolving references..."
uv run python -m src.cli.core_collect resolve-refs --create-stubs

# Step 8: Enrich stub papers
echo ""
echo "[Step 8] Enriching stub papers..."
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --parallel "$PARALLEL"

# Step 9: Incrementally update cited_by index (optional)
if [ "$SKIP_GRAPH" = false ]; then
    echo ""
    echo "[Step 9] Updating cited_by index (incremental)..."
    uv run python -m src.cli.core_collect build-cited-by --incremental
fi

# Step 10: Embed new papers (incremental — skips already-embedded)
if [ "$SKIP_LABELING" = true ] && [ "$SKIP_EMBED" = false ]; then
    echo "[WARNING] --skip-labeling with embedding: new papers will be embedded without section vectors."
    echo "          Re-run without --skip-labeling later, then re-embed with --no-resume to get section vectors."
fi
if [ "$SKIP_EMBED" = false ]; then
    echo ""
    echo "[Step 10] Embedding new papers (section-level + BM25)..."
    uv run python -m src.cli.core_collect embed-papers --batch-size 16 --embed-batch-size 128
fi

# Weekly maintenance steps
if [ "$WEEKLY" = true ]; then
    echo ""
    echo "[Weekly] Recomputing semantic similarity graph..."
    uv run python -m src.cli.core_collect compute-similarity --batch-size 50

    echo ""
    echo "[Weekly] Recomputing graph analysis (PageRank, HITS, communities)..."
    uv run python -m src.cli.core_collect analyze-graph --store
fi

# Quarterly clustering
if [ "$CLUSTER" = true ]; then
    echo ""
    echo "[Quarterly] Recomputing UMAP + HDBSCAN topic clusters..."
    uv run python -m src.cli.core_collect compute-topics
fi

# Wait for S2 backlog if it was started
if [ -n "$S2_BACKLOG_PID" ]; then
    echo ""
    echo "[Waiting] S2 backlog enrichment still running (PID $S2_BACKLOG_PID)..."
    if ! wait "$S2_BACKLOG_PID"; then
        echo "[WARNING] S2 backlog enrichment failed (non-fatal)."
    else
        echo "[Done] S2 backlog enrichment finished."
    fi
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

# Write pipeline status file for dashboard
echo "{\"status\": \"success\", \"finished_at\": \"$(date -Iseconds)\", \"duration_seconds\": $DURATION, \"days\": $DAYS}" > "$STATUS_FILE"

# Show final stats
echo ""
uv run python -m src.cli.core_collect status
