#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

BATCH_SIZE=${BATCH_SIZE:-32}
CONCURRENCY=${CONCURRENCY:-4}
LIMIT=${LIMIT:-}

while [[ $# -gt 0 ]]; do
    case $1 in
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --batch-size N     Abstracts per Ollama request (default: 32)"
            echo "  --concurrency N    Parallel Ollama requests (default: 4)"
            echo "  --limit N          Max papers to embed"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Paper Embedding"
echo "=========================================="
echo "Model: qwen3-embedding:8b (1024d)"
echo "Batch Size: $BATCH_SIZE"
echo "Concurrency: $CONCURRENCY"
if [ -n "$LIMIT" ]; then
    echo "Limit: $LIMIT"
fi
echo "=========================================="

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Error: Ollama is not running. Start it with: ollama serve"
    exit 1
fi

# Check model is pulled
if ! curl -s http://localhost:11434/api/tags | grep -q "qwen3-embedding"; then
    echo "Pulling qwen3-embedding:8b model..."
    ollama pull qwen3-embedding:8b
fi

CMD="uv run python -m src.cli.core_collect embed-papers"
CMD="$CMD --batch-size $BATCH_SIZE"
CMD="$CMD --concurrency $CONCURRENCY"
if [ -n "$LIMIT" ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo ""
echo "=========================================="
echo "Embedding complete!"
echo "=========================================="
