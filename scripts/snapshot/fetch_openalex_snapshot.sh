#!/bin/bash
# Download the OpenAlex WORKS snapshot (anonymous, no AWS creds) to NFS SSD2.
# ~300GB — run operationally; resumable by re-running.
set -e
DEST="${OPENALEX_SNAPSHOT_DIR:-/mnt/nfs/ssd2/openalex_snapshot}"
mkdir -p "$DEST"
echo "[snapshot] syncing s3://openalex/data/works -> $DEST/data/works"
aws s3 sync "s3://openalex/data/works" "$DEST/data/works" --no-sign-request
echo "[snapshot] done. works dir: $DEST/data/works"
du -sh "$DEST/data/works" 2>/dev/null || true
