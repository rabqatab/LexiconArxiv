#!/bin/bash
# ACM-specific PDF reference extraction.
#
# Pipeline:
#   1. Backfill pdf_url for DBLP-sourced ACM papers that don't have one
#   2. Run enrich-5-refs-by-pdf-via-grobid scoped to DOI prefix 10.1145/
#      → PDFReferenceExtractor.download_pdf auto-routes ACM URLs through the
#        stealth browser downloader (src/core/enrichment/acm_browser.py)
#
# Requires:
#   - GROBID running at http://localhost:8070
#     docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
#   - Qdrant at the configured URL
#
# Environment:
#   PARALLEL      default 5      # ACM browser downloader is self-serializing
#                                 # via an internal lock; higher values just
#                                 # queue. Keep modest.
#   BATCH_SIZE    default 50
#   LIMIT         default unset  # stop after N papers (debug)
#   GROBID_URL    default http://localhost:8070
#   DRY_RUN       default 0      # set to 1 to only count
#   SKIP_BACKFILL default 0

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

PARALLEL="${PARALLEL:-5}"
BATCH_SIZE="${BATCH_SIZE:-50}"
LIMIT="${LIMIT:-}"
GROBID_URL="${GROBID_URL:-http://localhost:8070}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_BACKFILL="${SKIP_BACKFILL:-0}"

# Parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)       DRY_RUN=1; shift ;;
    --skip-backfill) SKIP_BACKFILL=1; shift ;;
    --limit)         LIMIT="$2"; shift 2 ;;
    --parallel)      PARALLEL="$2"; shift 2 ;;
    --batch-size)    BATCH_SIZE="$2"; shift 2 ;;
    --grobid-url)    GROBID_URL="$2"; shift 2 ;;
    -h|--help)
      sed -n '/^#/p' "$0" | head -40
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

log "=== ACM PDF reference extraction ==="
log "Settings: parallel=$PARALLEL batch_size=$BATCH_SIZE limit=${LIMIT:-all} dry_run=$DRY_RUN"

# -- Step 1: backfill synthetic pdf_url for ACM papers that lack one
if [[ "$SKIP_BACKFILL" != "1" ]]; then
  log "--- Step 1/2: backfill pdf_url for ACM papers without one ---"
  if [[ "$DRY_RUN" == "1" ]]; then
    uv run python scripts/enrichment/backfill_acm_pdf_urls.py --dry-run
  else
    uv run python scripts/enrichment/backfill_acm_pdf_urls.py
  fi
else
  log "--- Step 1/2: skipped (--skip-backfill) ---"
fi

# -- Step 2: run the reference extraction scoped to 10.1145/
log "--- Step 2/2: enrich-5-refs-by-pdf-via-grobid --doi-prefix 10.1145/ ---"

CMD=(uv run python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid
     --doi-prefix "10.1145/"
     --parallel "$PARALLEL"
     --batch-size "$BATCH_SIZE"
     --grobid-url "$GROBID_URL"
     --retry-incomplete)  # safe: query filter (IsEmpty refs) already excludes successes

if [[ "$DRY_RUN" == "1" ]]; then
  CMD+=(--dry-run)
fi
if [[ -n "$LIMIT" ]]; then
  CMD+=(--limit "$LIMIT")
fi

log "Running: ${CMD[*]}"
"${CMD[@]}"

log "=== ACM PDF extraction complete ==="
