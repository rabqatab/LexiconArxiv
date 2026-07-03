#!/bin/bash
# Post-P3 embed-drain concurrency benchmark.
#
# Runs `embed-papers --consume-snapshot-queue --limit N` at three
# concurrency settings and reports elapsed time for each. Uses the real
# queue (backed up first) — the papers embedded during the bench are
# real and stay embedded, which is fine.
#
# Read the strategy doc before running:
#   docs/runbooks/embed-drain-strategy.md
#
# Usage:  ./scripts/embedding/benchmark_drain.sh [SAMPLE_SIZE]
# Default sample: 5000 papers.

set -euo pipefail

SAMPLE="${1:-5000}"
QUEUE="$HOME/dagster_home/snapshot_checkpoints/embedding_queue.jsonl"
BACKUP="$QUEUE.pre-bench.$(date -u +%Y%m%dT%H%M%SZ)"

if [ ! -f "$QUEUE" ]; then
    echo "ERROR: queue file not found: $QUEUE" >&2
    echo "  P3 may not have started, or DAGSTER_HOME points elsewhere." >&2
    exit 1
fi

# Sanity check — need enough headroom for 3 × sample size
QUEUE_DEPTH=$(uv run python -c "
from src.core.snapshot import embedding_queue
print(len(embedding_queue.peek_all()))
" 2>/dev/null)

if [ "$QUEUE_DEPTH" -lt "$((SAMPLE * 3))" ]; then
    echo "WARN: queue depth ($QUEUE_DEPTH) < 3 × sample ($SAMPLE)."
    echo "  Later benchmarks will drain fewer papers than earlier ones —"
    echo "  results won't be comparable. Consider reducing SAMPLE."
    read -p "  Continue anyway? [y/N] " REPLY
    [[ "$REPLY" =~ ^[Yy]$ ]] || exit 1
fi

echo "Backing up queue: $BACKUP"
cp "$QUEUE" "$BACKUP"

RESULTS=()
for P in 4 8 12; do
    echo ""
    echo "=== -p $P ==="
    START=$(date +%s)
    uv run python -m src.cli.core_collect embed-papers \
        --consume-snapshot-queue \
        --limit "$SAMPLE" \
        -p "$P" \
        --batch-size 8 \
        --embed-batch-size 64 \
        2>&1 | tail -8
    END=$(date +%s)
    ELAPSED=$((END - START))
    THROUGHPUT=$((SAMPLE * 3600 / ELAPSED))
    RESULTS+=("-p $P: ${ELAPSED}s (${THROUGHPUT}/hr)")
    echo "  -> ${ELAPSED}s elapsed, ${THROUGHPUT} papers/hr projected"
done

echo ""
echo "==========================================="
echo "Benchmark summary (sample=$SAMPLE papers):"
for R in "${RESULTS[@]}"; do
    echo "  $R"
done
echo ""
echo "Interpretation:"
echo "  Pick the -p that finishes fastest without 'Ollama connection refused'"
echo "  errors in the logs. If two settings are within ~10%, prefer the lower."
echo "  Feed the winner into the priority-tier + full-drain sparkq jobs — see"
echo "  docs/runbooks/embed-drain-strategy.md."
echo ""
echo "Queue backup preserved at: $BACKUP"
echo "  Remove after you're confident the drain is progressing normally:"
echo "  rm $BACKUP"
