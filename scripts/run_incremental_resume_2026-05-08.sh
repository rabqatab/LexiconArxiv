#!/bin/bash
# One-shot resume wrapper for the May 7 → May 8 incremental run that crashed
# at Step 9 (build_cited_by_incremental 404). Steps 1-8 already completed and
# their state is durable in Qdrant; this picks up from there.

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PARALLEL=5
START=$(date +%s)

echo "=============================================="
echo "[RESUME] Starting at $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

echo "[RESUME-Step 9] Updating cited_by index (incremental, post-fix)..."
uv run python -m src.cli.core_collect build-cited-by --incremental

echo "[RESUME-Step 10] Embedding new papers..."
uv run python -m src.cli.core_collect embed-papers --batch-size 16 --embed-batch-size 128

echo "[RESUME-Step 11] ACM stealth-browser PDF refs (10.1145/* DOIs only)..."
uv run python scripts/enrichment/backfill_acm_pdf_urls.py
uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid \
    --doi-prefix 10.1145/ --retry-incomplete --parallel "$PARALLEL"

END=$(date +%s)
DURATION=$((END - START))
MIN=$((DURATION / 60))
SEC=$((DURATION % 60))

echo "=============================================="
echo "[RESUME COMPLETE] Duration: ${MIN}m ${SEC}s"
echo "=============================================="

echo "{\"status\": \"success\", \"finished_at\": \"$(date -Iseconds)\", \"duration_seconds\": $DURATION, \"days\": 25, \"resumed_from\": \"step9\"}" > data/core/pipeline_status.json
