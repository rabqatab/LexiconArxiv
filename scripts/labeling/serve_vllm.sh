#!/bin/bash
# Launch vLLM server for bootstrap-scale abstract labeling.
#
# Usage:
#   Direct (foreground, for debugging):
#     ./scripts/labeling/serve_vllm.sh
#
#   Via sparkq (recommended — persistent for the labeling window):
#     sparkq submit "./scripts/labeling/serve_vllm.sh" \
#       --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
#       --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
#       --idempotency-key vllm-labeling-2026-07-04 --json
#
# Model: ibm-granite/granite-4.1-8b (same family as our Ollama default).
# Serves an OpenAI-compatible API at :8000; consumed by
# `label-abstracts --backend vllm`.
#
# See docs/design/vllm-labeling-migration.md for the full plan.

set -euo pipefail

MODEL="${VLLM_MODEL:-ibm-granite/granite-4.1-8b}"
PORT="${VLLM_PORT:-8000}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.30}"   # ~38G on 128G GB10 unified pool
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-4096}"  # abstract labeling never needs more
HF_CACHE="${HF_HOME:-/mnt/nfs/ssd1/huggingface_cache}"

export HF_HOME="$HF_CACHE"
export HF_HUB_ENABLE_HF_TRANSFER=1  # faster download on first run

echo "======================================================================="
echo "vLLM abstract-labeling server"
echo "  model:              $MODEL"
echo "  port:               $PORT"
echo "  gpu_mem_util:       $GPU_MEM_UTIL (of unified pool)"
echo "  max_model_len:      $MAX_MODEL_LEN"
echo "  HF cache:           $HF_CACHE"
echo "======================================================================="

# vLLM is not a project dep — install into an ephemeral uv env for the sparkq
# job's lifetime. Alternative: add vllm to pyproject.toml [gpu] extra.
uv pip install --quiet vllm

exec uv run python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --port "$PORT" \
    --host 0.0.0.0 \
    --dtype bfloat16 \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --max-model-len "$MAX_MODEL_LEN" \
    --guided-decoding-backend xgrammar \
    --disable-log-requests
