# vLLM Labeling Server — Operations Runbook

**What this runbook does:** stands up, monitors, restarts, and tears down the vLLM abstract-labeling server used by `label-abstracts --backend vllm`. It is the operational counterpart to the design in [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md).

**Related:** [`embed-drain-strategy.md`](embed-drain-strategy.md), [`post-bootstrap-catchup.md`](post-bootstrap-catchup.md), [`labeling-llm-comparison.md`](../reference/labeling-llm-comparison.md).

---

## When to use / When NOT to use

**Use vLLM labeling when:**

- Running production labeling on the post-bootstrap corpus (Step 1 of [`post-bootstrap-catchup.md`](post-bootstrap-catchup.md)) — anything at bulk P2/P3 scale.
- Any incremental cycle whose labeling backlog exceeds **~5,000 papers/week**. Ollama's serial-chat ceiling (~750 papers/hr) puts a 5K week at ~7 hours; anything larger pays too much wall clock.
- Any run where `label-abstracts --backend vllm` is the documented default (all production labeling per the 2026-07-04 policy update).

**Do NOT use vLLM labeling when:**

- Working on a dev laptop / any machine without a GB10 (or comparable) GPU. Fall back to `label-abstracts --backend ollama`.
- The weekly incremental backlog is under ~5,000 papers *and* Ollama's `granite4.1:8b` is already warm. The vLLM boot cost (job queue wait + model load) is not worth it at that volume.
- Doing a one-off eval of ≤200 papers where Ollama round-trip is easier to reason about.

Rule of thumb: if wall-clock at Ollama's ~750/hr would take **less than an hour**, keep Ollama. Everything else → vLLM.

---

## Preconditions

Run these checks in order. All must pass before submitting the vLLM job.

```bash
# 1. sparkq daemon healthy
sparkq health --json | jq '.status'   # expect: "healthy"

# 2. HF cache reachable (both read and write)
ls /mnt/nfs/ssd1/huggingface_cache/hub >/dev/null && echo "HF cache OK"

# 3. Model weights present (or willing to download ~16 GB on first run)
HF_HOME=/mnt/nfs/ssd1/huggingface_cache uv run python -c \
    "from transformers import AutoTokenizer; \
     AutoTokenizer.from_pretrained('ibm-granite/granite-4.1-8b'); \
     print('tokenizer OK')"

# 4. No Ollama chat model hogging the GPU (embedder-only is fine)
curl -s http://localhost:11434/api/ps | jq '.models[].name'
# If a chat model (granite4.1, qwen2.5, etc.) is loaded, unload it
# via `ollama stop <model>` before submitting vLLM. Embed models
# (qwen3-embedding, nomic-embed-text) can co-reside if you have headroom
# but plan for vLLM to want ~38 G of the 128 G unified pool.

# 5. Port 8000 not in use
ss -ltn '( sport = :8000 )' | grep -q LISTEN && \
    echo "port 8000 busy — investigate" || echo "port free"
```

If any check fails, resolve before continuing. In particular a leaked previous vLLM server (check 5 hits) is the number-one reason boot silently succeeds but health checks never turn green.

---

## Boot sequence

Submit the launch script via sparkq. **Always** use `--json`, capture the `job_id`, and use an idempotency key of the form `vllm-labeling-YYYYMMDD` so re-submits don't stack.

```bash
JOB=$(sparkq submit "./scripts/labeling/serve_vllm.sh" \
    --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
    --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key vllm-labeling-$(date -u +%Y%m%d) \
    --json | jq -r .job_id)
echo "vLLM job: $JOB"
```

Sizing notes:

- `--gpu-mem 40G` matches the auto-raised footprint from `--gpu-memory-utilization 0.30 × 128G ≈ 38G`. sparkq's real-memory gate rounds up automatically, but declaring 40G here keeps `--dry-run` reads honest.
- `--cpu-mem 24G` covers the tokenizer + HF hub downloader + xgrammar compilation footprint.
- `--max-runtime 96h` is the outer safety kill for bulk drains. Reduce to `24h` for an incremental cycle to avoid a hung server holding the queue slot.

First-run vs warm boot:

- **First run on the node** (weights not in `$HF_HOME/hub`): expect ~5–10 min for HF download to the NFS SSD, then ~1–2 min for weight materialization on GPU. Watch download progress in `sparkq log $JOB -f`.
- **Warm boot** (weights cached): ~1–2 min total from `queued` → serving.

Live check that the server is actually serving:

```bash
# Blocks briefly on the first request while xgrammar warms up
curl -s http://localhost:8000/v1/models | jq '.data[0].id'
# expect: "ibm-granite/granite-4.1-8b"
```

If `/v1/models` returns the model id, labeling clients (`label-abstracts --backend vllm`) can start. If it 404s, the process is still importing vLLM — check the log.

---

## Healthcheck monitoring

Once serving, monitor via a mix of sparkq state and vLLM's own log lines.

**sparkq view:**

```bash
sparkq status "$JOB" --json | jq '{status, pid_alive, elapsed_sec, deferred_reason}'
```

Watch for:

- `status: "running"` and `pid_alive: true` — healthy.
- `status: "queued"` with a `deferred_reason` mentioning `low_free_mem` — another job hasn't released memory yet. Wait; do not resubmit.
- `pid_alive: false` while `status: "running"` — daemon drift. Run `sparkq doctor` and see [Restart procedure](#restart-procedure).

**vLLM log grep patterns:**

```bash
sparkq log "$JOB" --lines 200 | grep -E \
    "Application startup complete|GPU KV cache|xgrammar|error|CUDA out of memory"
```

The load-bearing green lines:

- `Application startup complete.` — Uvicorn is bound to `:8000`. This is the definitive "server up" signal.
- `# GPU blocks: <N>` / `GPU KV cache size: <MB>` — KV cache allocated successfully; batched decoding will work.
- `Loading model weights took` — weight upload to GPU finished. Only appears once per boot.

Slow-load diagnosis (nothing appears for >30 min):

- If the last visible line is a `snapshot download` progress bar — HF is slow. Check `iostat -x 1 /mnt/nfs/ssd1` from another shell; if `%util` is high, NFS itself is saturated. Wait or fall back to Ollama for this cycle.
- If the last line is `Loading model weights` with no percentage — CUDA is stuck. `sparkq log $JOB -f` for another 5 min, then treat as a crash (Restart procedure).
- If `sparkq log` shows nothing at all after 2 min — the sparkq-side child hasn't started yet; check `sparkq doctor` for admission-gate deferral (`deferred_reason`).

---

## Restart procedure

Restarts follow the same idempotency-key discipline as the initial boot. Re-using the key lets sparkq decide whether it's a genuine restart or a stray double-submit.

```bash
# 1. Cancel — SIGTERMs the process group, waits 10s, then SIGKILLs.
sparkq cancel "$JOB" --json | jq '.'

# 2. Confirm the vLLM process is actually gone.
sparkq doctor --json | jq '.untracked_gpu_procs, .drifted_jobs'
#   Both should be empty arrays. If `untracked_gpu_procs` still lists
#   `python -m vllm...`, kill by PID: `kill -9 <pid>` and re-check.

# 3. Confirm nothing is bound to :8000.
ss -ltnp '( sport = :8000 )'
#   If a stray listener persists (very rare), the parent process is
#   zombied — reboot the node is the last resort; usually just wait.

# 4. Resubmit with the SAME idempotency key.
sparkq submit "./scripts/labeling/serve_vllm.sh" \
    --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
    --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key vllm-labeling-$(date -u +%Y%m%d) --json
```

Behavior of the idempotent submit:

- If the previous job actually terminated (Step 1 succeeded), sparkq queues a fresh run and returns the new `job_id`.
- If the previous job is still alive (Step 1 failed and you didn't notice), sparkq returns `"idempotent_hit": true` with the *existing* `job_id` — do not force a duplicate with `--allow-duplicates` unless you've truly killed the old one; two vLLM servers on the same port will fight and both crash.

Common restart triggers and their proper fixes:

- **OOM during a batch** (`CUDA out of memory` in log) — bump `--gpu-mem 40G → 60G` on next submit and lower `VLLM_GPU_MEM_UTIL` if concurrent tenants exist. Do NOT just retry.
- **Stuck HF download** (partial file in cache) — remove the specific model dir before resubmit:
  ```bash
  rm -rf /mnt/nfs/ssd1/huggingface_cache/hub/models--ibm-granite--granite-4.1-8b
  ```
  Then resubmit; the next run re-downloads clean.
- **CUDA driver hiccup** (`RuntimeError: CUDA error: unknown error` at startup) — not a vLLM bug. Check `nvidia-smi` on both nodes; if the driver is wedged, escalate to a node reboot per [`dgx-spark-gpu` skill](../../CLAUDE.md).

---

## Troubleshooting matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| `OSError: CUDA out of memory` at boot | Footprint too small vs model + KV cache | Raise `VLLM_GPU_MEM_UTIL` to `0.40` (or lower it to `0.20` and reduce `--max-model-len` if OOM is on KV, not weights). Bump sparkq `--gpu-mem` to match. |
| `Model loading stalled` for >30 min, no log progress | NFS mount slow, or partial/corrupt HF snapshot | `iostat -x 1 /mnt/nfs/ssd1` to confirm; `rm -rf $HF_HOME/hub/models--ibm-granite--granite-4.1-8b` and resubmit for a clean download. |
| `Port 8000 already in use` in the vLLM log | Previous vLLM process leaked past sparkq cancel | `ss -ltnp '( sport = :8000 )'`, `kill -9 <pid>`, then re-run `sparkq doctor` to confirm clean. Only then resubmit. |
| `guided_json` decoding raises validation errors from every request | xgrammar version mismatch with installed vLLM | Force reinstall the extras: `uv pip install --force-reinstall 'xgrammar>=0.1.0' vllm`. Verify with `uv pip show xgrammar vllm`. |
| `/v1/models` 404s but process is running | vLLM crashed inside its own event loop after startup print | Check `sparkq log $JOB --lines 500` for traceback — usually a `xgrammar` compile failure on the first `guided_json` request. Restart with the same idempotency key. |
| Very low throughput (<5K papers/hr) despite fit | `--vllm-max-concurrent` set too low client-side | Bump `label-abstracts --vllm-max-concurrent` (32 → 64 → 96) and re-measure. Server-side raise `VLLM_GPU_MEM_UTIL` for more KV cache. |
| sparkq says `deferred_reason: low_free_mem` for 10+ min | Real free RAM below the min_free_mb gate | `sparkq doctor --json` — check `untracked_gpu_procs` for orphans (Ollama chat model?). Unload orphans, then the job admits automatically. |
| `pid_alive: false` while `status: running` | Daemon lost track of the child (rare) | `sparkq doctor` will flag `drifted_jobs`. Cancel the drifted id and resubmit. |

---

## Shutdown

Clean shutdown when a labeling drain finishes:

```bash
# 1. Cancel the sparkq job.
sparkq cancel "$JOB" --json | jq '.'

# 2. Verify the server is refusing connections.
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/models
# expect: 000 (connection refused) or a similar transport error, NOT 200.

# 3. Confirm no orphaned GPU process is holding memory.
sparkq doctor --json | jq '.untracked_gpu_procs'
# expect: []
```

If step 3 shows a stray `python -m vllm...`, kill it by PID before submitting the next GPU job — the real-memory gate will otherwise misjudge free memory for the next admission.

For a scheduled labeling window (e.g. an overnight incremental cycle), prefer `--max-runtime` on the initial submit over manual shutdown; the auto-kill leaves clean state and no operator round-trip.

---

## Cross-refs

- Design: [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) — quality/throughput gates, model choice rationale, rollback semantics.
- Upstream step: [`docs/runbooks/post-bootstrap-catchup.md`](post-bootstrap-catchup.md) — Step 1 (labeling) invokes this runbook.
- Downstream step: [`docs/runbooks/embed-drain-strategy.md`](embed-drain-strategy.md) — must not start until labeling is complete on the target subset.
- Backend eval: [`docs/reference/labeling-llm-comparison.md`](../reference/labeling-llm-comparison.md) — why `granite4.1:8b` / `ibm-granite/granite-4.1-8b` is the incumbent.
- sparkq mechanics: `~/.claude/skills/sparkq/SKILL.md` — `--idempotency-key`, `--after`, `--max-runtime`, `--json` patterns used above.
- Hardware quirks: `dgx-spark-gpu` skill — SM 12.1 workarounds relevant when vLLM boot itself is unstable (rare).
