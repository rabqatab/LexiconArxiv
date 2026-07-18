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
# DAYS_MARGIN must be defined BEFORE first use (Step 4b/4c GROBID) — the
# 2026-07-08 5fe7 run passed --recent-days '' because this lived below the
# GROBID block, silently skipping both GROBID steps.
DAYS_MARGIN=$((DAYS + 2))
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
    echo "  8.5. reconcile-stubs --recent-days $DAYS_MARGIN (promote stubs shadowed by new papers)"
    if [ "$SKIP_GRAPH" = false ]; then
        echo "  9. build-cited-by --incremental"
    fi
    if [ "$SKIP_EMBED" = false ]; then
        echo " 10. embed-papers (section-level + BM25 vectors)"
    fi
    if [ "$WEEKLY" = true ]; then
        echo " 11. compute-similarity (semantic similarity graph)"
        echo " 12. analyze-citation-graph --all --store (PageRank, HITS, communities)"
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
# Path B (2026-07-06): --recent-days derived from the pipeline's --days arg
# with a small safety margin. Without it the enricher scans all 3.7M+
# papers for empty abstracts on the unindexed field, hitting Qdrant's
# 60s scroll_by_id timeout. See docs/design/bulk-vs-incremental-audit.md.
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex \
    --parallel "$PARALLEL" \
    --recent-days "$((DAYS + 2))"

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
uv run python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel "$PARALLEL" --recent-days "$((DAYS + 2))"

# Step 4b: GROBID PDF-based refs (fallback for ACL/DBLP papers where
# CrossRef+S2 failed — 2026-07-07 discovery: 90% of recent non-stub
# real papers still had no referenced_works after Step 3a+4 because
# CrossRef doesn't cover ACL and S2 doesn't cover a huge chunk of
# older refs). GROBID needs a running Docker container (see doc
# comment in enrich-5 CLI). Gracefully skipped when GROBID is
# unreachable so a missing server does not stop the whole pipeline —
# a WARNING is logged, the next steps continue, and the incremental
# script's next weekly run picks up the backlog once GROBID is up.
# Only touches recent papers via --recent-days so it stays a
# true-incremental fallback rather than a full-corpus sweep.
GROBID_URL="${GROBID_URL:-http://localhost:8070}"
# grobid-arm64:latest is a locally-built aarch64 image — lfoppiano/grobid
# is amd64-only and silently fails to boot on the DGX Spark (2026-07-07
# 7a34: container started, never answered /api/isalive, auto-skip fired).
GROBID_IMAGE="${GROBID_IMAGE:-grobid-arm64:latest}"
GROBID_CONTAINER="${GROBID_CONTAINER:-lexicon-grobid}"
GROBID_AUTO_START="${GROBID_AUTO_START:-true}"   # set to "false" to disable auto-start
GROBID_STARTED_BY_US=false

echo ""
echo "[Step 4b] GROBID PDF refs (fallback for papers CrossRef+S2 missed) — recent papers only..."

# Auto-start GROBID container when unreachable. Docker socket is
# assumed available on the DGX Spark node; falls through to skip if
# not. Detached (-d) so the pipeline can proceed; container name is
# stable so a re-run finds and reuses the existing one instead of
# duplicating. We tear it down at pipeline end only when we were the
# ones who launched it (see cleanup at the bottom of this script).
grobid_alive() {
    curl -sf --max-time 3 "${GROBID_URL}/api/isalive" > /dev/null 2>&1
}

if ! grobid_alive && [ "$GROBID_AUTO_START" = "true" ]; then
    if command -v docker > /dev/null 2>&1; then
        # Reuse a stopped container if one exists; otherwise start fresh.
        if docker ps -a --format '{{.Names}}' | grep -q "^${GROBID_CONTAINER}$"; then
            echo "[Step 4b] Restarting existing GROBID container ${GROBID_CONTAINER}..."
            docker start "$GROBID_CONTAINER" > /dev/null || true
        else
            echo "[Step 4b] Starting GROBID container ${GROBID_CONTAINER} (${GROBID_IMAGE})..."
            docker run -d --rm --name "$GROBID_CONTAINER" -p 8070:8070 "$GROBID_IMAGE" > /dev/null || true
        fi
        GROBID_STARTED_BY_US=true
        # Poll /api/isalive up to 90 s — first-time image pull can be slow.
        for i in $(seq 1 45); do
            if grobid_alive; then
                echo "[Step 4b] GROBID ready after ${i}×2s poll."
                break
            fi
            sleep 2
        done
    else
        echo "[Step 4b] docker CLI not found — cannot auto-start GROBID."
    fi
fi

if grobid_alive; then
    if ! uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid \
        --parallel "$PARALLEL" --recent-days "$DAYS_MARGIN" \
        --grobid-url "$GROBID_URL"; then
        echo "[WARNING] GROBID refs extraction returned non-zero — continuing pipeline."
    fi
    # Step 4c: GROBID PDF-based abstracts. Small volume (2026-07-07:
    # ~700 recent non-stub papers with empty abstract) but valuable —
    # every unlabeled non-stub abstract is a search-relevance gap.
    echo ""
    echo "[Step 4c] GROBID PDF abstracts (fallback for papers OpenAlex missed) — recent papers only..."
    if ! uv run python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid \
        --parallel "$PARALLEL" --recent-days "$DAYS_MARGIN" \
        --grobid-url "$GROBID_URL"; then
        echo "[WARNING] GROBID abstract extraction returned non-zero — continuing pipeline."
    fi
else
    echo "[SKIP] GROBID not reachable at ${GROBID_URL} — Step 4b/4c skipped."
    echo "       Manual start: docker run --rm -p 8070:8070 ${GROBID_IMAGE}"
    echo "       Or disable auto-start: GROBID_AUTO_START=false"
fi

# GROBID container teardown — only if we were the ones who launched it.
# Detached container keeps running otherwise so an operator who started
# it manually retains their instance for reuse.
if [ "$GROBID_STARTED_BY_US" = "true" ]; then
    echo ""
    echo "[Step 4d] Stopping GROBID container ${GROBID_CONTAINER}..."
    docker stop "$GROBID_CONTAINER" > /dev/null 2>&1 || true
fi

# Steps 5+6: Keywords & Labeling — SERIAL per Path B (2026-07-04).
# The prior parallel pattern crashed Qdrant with concurrent bulk write
# clients during the 2026-07-04 catchup (be19 + 09a1). See:
# - docs/design/bulk-vs-incremental-audit.md §Bulk-write concurrency rule
# - docs/runbooks/post-bootstrap-catchup.md §Bulk write concurrency
# Labeling backend is vLLM at bulk scale (Ollama chat retired from
# pipelines); server must be running per docs/runbooks/vllm-labeling.md.

# Path B + true-incremental rule (2026-07-07): every step must be
# scoped via --recent-days so the incremental script processes only
# today's new papers, not the multi-million-point unlabeled/
# unkeyworded/unembedded backlog (2026-07-06 c0c7 discovery — the
# label-abstracts + extract-keywords + embed-papers CLIs default to
# full-corpus sweep, which turned a "fill 33-day gap" incremental
# run into a 40-day bulk labeling job). Backlog cleanup remains a
# separate concern (Wave 4b/4c type + topic filters + explicit
# bulk-labeling script).

echo ""
echo "[Step 5] Extracting keywords (regex + KeyBERT; no LLM) — recent papers only..."
if ! uv run python -m src.cli.core_collect extract-keywords --recent-days "$DAYS_MARGIN"; then
    echo "[ERROR] Keyword extraction failed."
    exit 1
fi

if [ "$SKIP_LABELING" = false ]; then
    echo ""
    echo "[Step 6] Labeling abstracts (vLLM backend) — recent papers only..."
    if ! uv run python -m src.cli.core_collect label-abstracts --backend vllm --recent-days "$DAYS_MARGIN"; then
        echo "[ERROR] Abstract labeling failed."
        exit 1
    fi
fi

# Step 7: Resolve references and create stubs — recent papers only
# ORDERING NOTE: resolve-refs runs AFTER keywords(5)/labeling(6) here, the
# reverse of run_full_pipeline.sh (crawler bulk runs Resolution before them).
# Both are correct — keyword/label read only the paper's own title/abstract and
# do not depend on resolution. Order differs for historical reasons only.
# (Wave 1e-quinquies, 2026-07-07: 21fe spent 7+ h in Step 7.1 Normalize
# alone because the resolver's 3 sub-steps swept the full 2.8 M-paper
# referenced_works backlog on every incremental cycle. --recent-days
# now threads through normalize / arxiv / internal via the resolver's
# run_full_pipeline signature.)
echo ""
echo "[Step 7] Resolving references — recent papers only..."
uv run python -m src.cli.core_collect resolve-refs --create-stubs --recent-days "$DAYS_MARGIN"

# Step 8: Enrich stub papers
# Similar to Step 7 — enrich-8 sweeps all stubs missing metadata.
# Left as-is; new stubs from Step 7 are the main target and the sweep
# converges quickly on a healthy corpus.
echo ""
echo "[Step 8] Enriching stub papers..."
uv run python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --parallel "$PARALLEL"

# Step 8.5: Reconcile stub duplicates — promote stubs shadowed by newly
# collected real papers, preserving their cited_by. Runs BEFORE build-cited-by
# so citation counts land on the promoted real paper, not an orphaned stub.
# Scoped to recent papers (bulk-safe: bootstrap has no stubs to reconcile).
echo ""
echo "[Step 8.5] Reconciling stub duplicates (promote shadowed stubs)..."
uv run python -m src.cli.core_collect reconcile-stubs --recent-days "$DAYS_MARGIN"

# Step 9: Incrementally update cited_by index (optional)
if [ "$SKIP_GRAPH" = false ]; then
    echo ""
    echo "[Step 9] Updating cited_by index (incremental)..."
    uv run python -m src.cli.core_collect build-cited-by --incremental
fi

# Step 10: Embed new papers (true-incremental — recent papers only)
if [ "$SKIP_LABELING" = true ] && [ "$SKIP_EMBED" = false ]; then
    echo "[WARNING] --skip-labeling with embedding: new papers will be embedded without section vectors."
    echo "          Re-run without --skip-labeling later, then re-embed with --no-resume to get section vectors."
fi
if [ "$SKIP_EMBED" = false ]; then
    echo ""
    echo "[Step 10] Embedding new papers (section-level + BM25) — recent papers only..."
    uv run python -m src.cli.core_collect embed-papers --batch-size 16 --embed-batch-size 128 --recent-days "$DAYS_MARGIN"
fi

# Weekly maintenance steps
if [ "$WEEKLY" = true ]; then
    echo ""
    echo "[Weekly] Recomputing semantic similarity graph..."
    uv run python -m src.cli.core_collect compute-similarity --batch-size 50

    echo ""
    echo "[Weekly] Recomputing graph analysis (PageRank, HITS, communities)..."
    uv run python -m src.cli.core_collect analyze-citation-graph --all --store
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
