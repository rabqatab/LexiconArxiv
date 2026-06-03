#!/bin/bash
# One-shot resume wrapper for the 2026-06-03 incremental run (--days 30 --weekly
# --cluster) that crashed at Step 12: the orchestrator called the non-existent
# command `analyze-graph` (real command is `analyze-citation-graph`), so Click
# exited 2. Steps 1-11 completed and their state is durable in Qdrant (including
# the similarity graph). This picks up from Step 12.

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

STATUS_FILE="data/core/pipeline_status.json"
trap 'echo "{\"status\": \"failed\", \"finished_at\": \"$(date -Iseconds)\", \"error\": \"Resume failed\", \"days\": 30, \"resumed_from\": \"step12\"}" > "$STATUS_FILE"' ERR

START=$(date +%s)

echo "=============================================="
echo "[RESUME] Starting at $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

echo "[RESUME-Step 12] Graph analysis (PageRank, HITS, communities)..."
uv run python -m src.cli.core_collect analyze-citation-graph --all --store

echo "[RESUME-Step 13] Topic re-clustering (UMAP + HDBSCAN)..."
uv run python -m src.cli.core_collect compute-topics

END=$(date +%s)
DURATION=$((END - START))
MIN=$((DURATION / 60))
SEC=$((DURATION % 60))

echo "=============================================="
echo "[RESUME COMPLETE] Duration: ${MIN}m ${SEC}s"
echo "=============================================="

echo "{\"status\": \"success\", \"finished_at\": \"$(date -Iseconds)\", \"duration_seconds\": $DURATION, \"days\": 30, \"resumed_from\": \"step12\"}" > "$STATUS_FILE"

echo ""
uv run python -m src.cli.core_collect status
