#!/bin/bash
# Helper script to set up crontab for incremental collection
# Run with --install to add the cron job, --remove to remove it

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default schedule: daily at 2 AM
CRON_SCHEDULE=${CRON_SCHEDULE:-"0 2 * * *"}
LOG_DIR=${LOG_DIR:-"/var/log"}
LOG_FILE="$LOG_DIR/lexicon_crawler.log"

# Cron job command
CRON_CMD="$SCRIPT_DIR/run_incremental.sh >> $LOG_FILE 2>&1"
CRON_LINE="$CRON_SCHEDULE $CRON_CMD"
CRON_MARKER="# LexiconArxiv incremental crawler"

show_help() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  --show      Show current crontab entries"
    echo "  --install   Install the cron job"
    echo "  --remove    Remove the cron job"
    echo "  --help      Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  CRON_SCHEDULE  Cron schedule (default: '0 2 * * *' = daily at 2 AM)"
    echo "  LOG_DIR        Log directory (default: /var/log)"
    echo ""
    echo "Example schedules:"
    echo "  '0 2 * * *'     Daily at 2:00 AM"
    echo "  '0 */6 * * *'   Every 6 hours"
    echo "  '0 2 * * 0'     Weekly on Sunday at 2:00 AM"
}

show_crontab() {
    echo "Current crontab:"
    echo "----------------"
    crontab -l 2>/dev/null || echo "(no crontab)"
}

install_cron() {
    echo "Installing cron job..."
    echo ""
    echo "Schedule: $CRON_SCHEDULE"
    echo "Command: $CRON_CMD"
    echo "Log file: $LOG_FILE"
    echo ""

    # Check if log directory is writable
    if [ ! -w "$LOG_DIR" ]; then
        echo "Warning: Log directory $LOG_DIR is not writable."
        echo "You may need to create it or use a different LOG_DIR:"
        echo "  sudo mkdir -p $LOG_DIR && sudo chown \$USER $LOG_DIR"
        echo "  or"
        echo "  LOG_DIR=\$HOME/logs $0 --install"
        echo ""
    fi

    # Get current crontab (or empty if none)
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)

    # Check if already installed
    if echo "$CURRENT_CRON" | grep -q "LexiconArxiv incremental crawler"; then
        echo "Cron job already exists. Remove it first with --remove"
        exit 1
    fi

    # Add new cron job
    (echo "$CURRENT_CRON"; echo "$CRON_MARKER"; echo "$CRON_LINE") | crontab -

    echo "Cron job installed successfully!"
    echo ""
    show_crontab
}

remove_cron() {
    echo "Removing cron job..."

    # Get current crontab
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)

    if [ -z "$CURRENT_CRON" ]; then
        echo "No crontab found."
        exit 0
    fi

    # Remove LexiconArxiv entries
    NEW_CRON=$(echo "$CURRENT_CRON" | grep -v "LexiconArxiv" | grep -v "run_incremental.sh" || true)

    if [ -z "$NEW_CRON" ]; then
        crontab -r 2>/dev/null || true
        echo "Crontab cleared."
    else
        echo "$NEW_CRON" | crontab -
        echo "Cron job removed."
    fi

    echo ""
    show_crontab
}

# Parse command
case "${1:-}" in
    --show)
        show_crontab
        ;;
    --install)
        install_cron
        ;;
    --remove)
        remove_cron
        ;;
    --help|"")
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
