#!/bin/bash
# Launch vLLM server for bootstrap-scale abstract labeling.
#
# Uses the NGC pre-built vLLM container `nvcr.io/nvidia/vllm:25.11-py3`
# — the PyPI vllm wheels are x86_64/CUDA and fail to load
# `libtorch_cuda.so` on DGX Spark's aarch64 (Grace-Blackwell) — root
# cause of the 2026-07-04 first-boot failure.
#
# Usage:
#   Direct (foreground, for debugging):
#     ./scripts/labeling/serve_vllm.sh
#
#   Via sparkq (recommended — persistent for the labeling window):
#     sparkq submit "./scripts/labeling/serve_vllm.sh" \
#       --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
#       --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
#       --idempotency-key vllm-labeling-YYYYMMDD --json
#
# Model: ibm-granite/granite-4.1-8b (same family as our Ollama default).
# Serves an OpenAI-compatible API at :8000; consumed by
# `label-abstracts --backend vllm`.
#
# See docs/design/vllm-labeling-migration.md and
# docs/runbooks/vllm-labeling.md for the full plan + ops.

set -euo pipefail

MODEL="${VLLM_MODEL:-ibm-granite/granite-4.1-8b}"
PORT="${VLLM_PORT:-8000}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.30}"    # ~38G on 128G GB10 unified pool
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-4096}"  # abstract labeling never needs more
IMAGE="${VLLM_IMAGE:-nvcr.io/nvidia/vllm:25.11-py3}"
HF_CACHE="${HF_HOME:-/mnt/nfs/ssd1/huggingface_cache}"
CONTAINER_NAME="vllm-labeling-$$"

echo "======================================================================="
echo "vLLM abstract-labeling server (Nvidia container, aarch64)"
echo "  image:              $IMAGE"
echo "  model:              $MODEL"
echo "  port:               $PORT"
echo "  gpu_mem_util:       $GPU_MEM_UTIL (of unified pool)"
echo "  max_model_len:      $MAX_MODEL_LEN"
echo "  HF cache (host):    $HF_CACHE"
echo "  container name:     $CONTAINER_NAME"
echo "======================================================================="

# Ensure host cache dir exists so bind mount doesn't create it root-owned
mkdir -p "$HF_CACHE"

# Kill any leftover container from a previous run (idempotency-safe)
if docker ps -q --filter "name=^vllm-labeling-" | grep -q .; then
    echo "Stopping stale vllm-labeling container(s):"
    docker ps --filter "name=^vllm-labeling-" --format "  {{.Names}} (id={{.ID}})"
    docker ps -q --filter "name=^vllm-labeling-" | xargs -r docker stop
fi

# Clean shutdown when this script is killed (sparkq cancel → SIGTERM)
cleanup() {
    echo "Shutdown: stopping container $CONTAINER_NAME"
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm    "$CONTAINER_NAME" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# exec so the container's PID becomes our PID — sparkq's PID monitoring
# and SIGTERM propagation both work correctly.
exec docker run --rm \
    --name "$CONTAINER_NAME" \
    --gpus all \
    --network host \
    --ipc host \
    --shm-size 8g \
    -v "$HF_CACHE:/root/.cache/huggingface" \
    "$IMAGE" \
    vllm serve "$MODEL" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --dtype bfloat16 \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --max-model-len "$MAX_MODEL_LEN" \
        --guided-decoding-backend xgrammar \
        --disable-log-requests
