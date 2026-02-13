#!/bin/bash
# Qdrant Snapshot Management
# Creates, lists, and restores snapshots of the Qdrant collection.
#
# Usage:
#   ./scripts/maintenance/qdrant_snapshot.sh              # Create snapshot
#   ./scripts/maintenance/qdrant_snapshot.sh --list        # List snapshots
#   ./scripts/maintenance/qdrant_snapshot.sh --restore <file>  # Restore snapshot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION="${QDRANT_COLLECTION:-lexicon_arxiv}"
BACKUP_DIR="${PROJECT_ROOT}/data/backups"

# Parse arguments
ACTION="create"
RESTORE_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            ACTION="list"
            shift
            ;;
        --restore)
            ACTION="restore"
            RESTORE_FILE="$2"
            if [ -z "$RESTORE_FILE" ]; then
                echo "Error: --restore requires a snapshot file path"
                exit 1
            fi
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Manage Qdrant collection snapshots"
            echo ""
            echo "Options:"
            echo "  (no args)           Create a new snapshot"
            echo "  --list              List existing snapshots"
            echo "  --restore <file>    Restore from a snapshot file"
            echo "  --help              Show this help message"
            echo ""
            echo "Environment:"
            echo "  QDRANT_URL          Qdrant server URL (default: http://localhost:6333)"
            echo "  QDRANT_COLLECTION   Collection name (default: lexicon_arxiv)"
            echo ""
            echo "Examples:"
            echo "  $0                                          # Create snapshot"
            echo "  $0 --list                                   # List snapshots"
            echo "  $0 --restore data/backups/lexicon_arxiv_2026-02-13.snapshot"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check Qdrant connectivity
check_qdrant() {
    if ! curl -sf "${QDRANT_URL}/healthz" > /dev/null 2>&1; then
        echo "Error: Cannot connect to Qdrant at ${QDRANT_URL}"
        echo "Start Qdrant: docker run -d -p 6333:6333 --name qdrant -v qdrant_storage:/qdrant/storage qdrant/qdrant"
        exit 1
    fi
}

# Get collection point count
get_point_count() {
    local count
    count=$(curl -sf "${QDRANT_URL}/collections/${COLLECTION}" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])" 2>/dev/null)
    echo "${count:-0}"
}

# Create snapshot
create_snapshot() {
    check_qdrant

    local count
    count=$(get_point_count)

    if [ "$count" = "0" ]; then
        echo "Collection '${COLLECTION}' is empty (0 points). Nothing to snapshot."
        exit 0
    fi

    echo "Creating snapshot of '${COLLECTION}' (${count} points)..."

    mkdir -p "$BACKUP_DIR"

    # Trigger snapshot creation via Qdrant API
    local response
    response=$(curl -sf -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots")

    if [ $? -ne 0 ] || [ -z "$response" ]; then
        echo "Error: Failed to create snapshot"
        exit 1
    fi

    # Extract snapshot filename from response
    local snapshot_name
    snapshot_name=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['name'])" 2>/dev/null)

    if [ -z "$snapshot_name" ]; then
        echo "Error: Could not parse snapshot name from response"
        echo "Response: $response"
        exit 1
    fi

    # Download the snapshot
    local timestamp
    timestamp=$(date +%Y-%m-%d_%H%M%S)
    local output_file="${BACKUP_DIR}/${COLLECTION}_${timestamp}.snapshot"

    echo "Downloading snapshot: ${snapshot_name}"
    curl -sf "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${snapshot_name}" -o "$output_file"

    if [ $? -ne 0 ]; then
        echo "Error: Failed to download snapshot"
        exit 1
    fi

    local size
    size=$(du -sh "$output_file" | cut -f1)
    echo "Snapshot saved: ${output_file} (${size})"
    echo "Collection: ${COLLECTION} | Points: ${count}"
}

# List snapshots
list_snapshots() {
    check_qdrant

    echo "=== Remote Snapshots (Qdrant server) ==="
    local response
    response=$(curl -sf "${QDRANT_URL}/collections/${COLLECTION}/snapshots")
    if [ $? -eq 0 ] && [ -n "$response" ]; then
        echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
snapshots = data.get('result', [])
if not snapshots:
    print('  (none)')
else:
    for s in snapshots:
        size_mb = s.get('size', 0) / (1024*1024)
        print(f\"  {s['name']}  ({size_mb:.1f} MB)  created: {s.get('creation_time', 'unknown')}\")
" 2>/dev/null
    else
        echo "  (could not fetch remote snapshots)"
    fi

    echo ""
    echo "=== Local Backups (${BACKUP_DIR}) ==="
    if [ -d "$BACKUP_DIR" ] && [ "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        ls -lh "$BACKUP_DIR"/*.snapshot 2>/dev/null | awk '{print "  "$NF" ("$5")"}'
    else
        echo "  (none)"
    fi
}

# Restore snapshot
restore_snapshot() {
    check_qdrant

    if [ ! -f "$RESTORE_FILE" ]; then
        echo "Error: Snapshot file not found: $RESTORE_FILE"
        exit 1
    fi

    local size
    size=$(du -sh "$RESTORE_FILE" | cut -f1)
    echo "Restoring snapshot: ${RESTORE_FILE} (${size})"
    echo "Collection: ${COLLECTION}"
    echo ""
    echo "WARNING: This will replace all data in '${COLLECTION}'!"
    read -p "Continue? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi

    echo "Uploading snapshot..."
    local response
    response=$(curl -sf -X POST \
        "${QDRANT_URL}/collections/${COLLECTION}/snapshots/upload" \
        -H "Content-Type: multipart/form-data" \
        -F "snapshot=@${RESTORE_FILE}")

    if [ $? -ne 0 ]; then
        echo "Error: Failed to upload snapshot"
        exit 1
    fi

    echo "Snapshot restored successfully."

    local count
    count=$(get_point_count)
    echo "Collection '${COLLECTION}' now has ${count} points."
}

# Main
case "$ACTION" in
    create)
        create_snapshot
        ;;
    list)
        list_snapshots
        ;;
    restore)
        restore_snapshot
        ;;
esac
