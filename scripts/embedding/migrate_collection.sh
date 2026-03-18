#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

NEW_COLLECTION=${NEW_COLLECTION:-}

echo "=========================================="
echo "LexiconArxiv Collection Migration"
echo "=========================================="
echo "Migrating payload-only → vector-enabled"
echo "=========================================="

CMD="uv run python -m src.cli.core_collect migrate-collection"
if [ -n "$NEW_COLLECTION" ]; then
    CMD="$CMD --new-collection $NEW_COLLECTION"
fi

$CMD

echo ""
echo "=========================================="
echo "Migration complete!"
echo "=========================================="
echo "Next: Update QDRANT_COLLECTION in .env, then run embedding."
