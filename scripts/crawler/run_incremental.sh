#!/bin/bash
# Incremental collection script for crontab
# Fetches papers updated in the last N days
#
# Crontab example (daily at 2 AM):
#   0 2 * * * /path/to/scripts/crawler/run_incremental.sh >> /var/log/lexicon_cron.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
DAYS_BACK=${DAYS_BACK:-1}
SOURCE=${SOURCE:-all}
LOG_FILE=${LOG_FILE:-""}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days)
            DAYS_BACK="$2"
            shift 2
            ;;
        --source)
            SOURCE="$2"
            shift 2
            ;;
        --log)
            LOG_FILE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --days N         Days to look back (default: 1)"
            echo "  --source SOURCE  Source to collect: all, openalex, acl, dblp (default: all)"
            echo "  --log FILE       Log file path (optional)"
            echo "  --help           Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  DAYS_BACK        Same as --days"
            echo "  SOURCE           Same as --source"
            echo "  LOG_FILE         Same as --log"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Timestamp for logging
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1"
}

log "Starting incremental collection (days=$DAYS_BACK, source=$SOURCE)"

# Run collection
CMD="uv run python -m src.cli.core_collect collect-incremental --days $DAYS_BACK --source $SOURCE"

if [ -n "$LOG_FILE" ]; then
    $CMD 2>&1 | tee -a "$LOG_FILE"
else
    $CMD
fi

log "Incremental collection complete"
