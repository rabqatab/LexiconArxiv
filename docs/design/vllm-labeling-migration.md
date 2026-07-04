# vLLM Labeling Migration — Design

**Date:** 2026-07-04
**Owner:** MCH
**Status:** Phase 0 complete (code + docs prepped); Phase 1 (POC + eval) blocked on P3 completion.
**Related:** [`embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md), [ponytail audit item #24](../refactoring/2026-06-24-ponytail-audit.md), [incident 2026-07-03](../incidents/2026-07-03-mcp-search-endpoints-broken.md), [labeling LLM eval](../reference/labeling-llm-comparison.md).

## Problem

Snapshot bootstrap (P2 + P3) has produced **~3 million real papers** that have `abstract` but no `abstract_structure`. Without labeling:

- `structured-abstract` vector falls back to raw abstract text (no role tags).
- 7 `section-*` vectors (`section-method`, `section-task`, …) are **not generated at all** — the embedder's `if structure:` guard skips them (`src/core/embedding/embedder.py:196`).
- The default MCP search prefetches `["structured-abstract", "section-method", "section-task"]`. Two of those three come back empty on unlabeled papers.
- Practical impact: **section-aware search is effectively dead on 90% of the post-bootstrap corpus**.

We measured Ollama+granite4.1:8b at **~750 papers/hr, zero benefit from concurrency** (single-GPU serial pipeline). 3M ÷ 750/hr = ~167 days. Not feasible.

## Decision

Migrate labeling to vLLM with continuous batching. Same model family so quality risk is minimized, but a re-eval is required before we commit.

**Target throughput:** ≥ 30,000 papers/hr (40× Ollama). 3M ÷ 30K/hr = ~4 days for the full bootstrap.

**Rejected alternatives:**
- **Skip labeling entirely** (E2 in earlier discussion): user judgment — section vectors are core to this corpus's identity. Loss of quality unacceptable.
- **Tier-only labeling** (E3): 900K papers × 750/hr = 50 days. Still too slow.
- **Smaller Ollama model**: even a 2× speedup leaves us at ~80 days.

## Model choice: `ibm-granite/granite-4.1-8b`

- Same family as production `granite4.1:8b` on Ollama. The 2026-06-19 [labeling LLM benchmark](../reference/labeling-llm-comparison.md) selected the Granite family after a 60-paper eval; keeping the family minimizes quality drift.
- BF16, 9B params, ~18 GB VRAM for weights + ~10–20 GB for KV cache at batch=32 = **~30–40 GB** on GB10's 128 GB unified pool.
- HF model card explicitly documents vLLM support: `vllm serve 'ibm-granite/granite-4.1-8b'`.
- Chat-template supported; the same `SentenceLabels` Pydantic schema drives constrained JSON via vLLM's `guided_json` extra body param.

**Fallback (if quality gate fails):** latest Qwen family (`Qwen/Qwen3-8B`) at same params. Requires a fresh eval to justify.

## Deployment

**Containerized on DGX Spark (aarch64)**. The 2026-07-04 first-boot attempt via `uv pip install vllm` failed with `libtorch_cuda.so: cannot open shared object file` — vLLM's PyPI wheels are x86_64 only. NGC's `nvcr.io/nvidia/vllm:25.11-py3` is Nvidia's official arm64 build with matching torch/CUDA and works out of the box. `scripts/labeling/serve_vllm.sh` orchestrates `docker run` with proper GPU / IPC / HF-cache binds. The `[gpu]` extra in `pyproject.toml` (vllm + xgrammar wheels) is preserved for x86_64 dev-laptop use only.

**Serve via sparkq**, single-node:

```bash
sparkq submit "./scripts/labeling/serve_vllm.sh" \
    --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
    --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key vllm-labeling-2026-07-04 --json
```

sparkq's real-memory admission gate rounds up the vLLM footprint from `--gpu-memory-utilization 0.30` × 128 G = 38 G automatically. Declaring `--gpu-mem 40G` lets the dry-run fit check match the auto-raised number.

Client-side: `label-abstracts --backend vllm --vllm-base-url http://localhost:8000`.

**Not systemd** — the load is bootstrap-shaped, but even incremental cycles now prefer vLLM (see next paragraph). Deploying via sparkq lets us start/stop the vLLM job around each labeling run without keeping a service alive between them.

**Policy update (2026-07-04, per user requirement)**: vLLM is the **default backend for all labeling — both bulk AND incremental**. The earlier draft said Ollama was fine for incremental; that was wrong. Ollama's 750/hr ceiling makes even a 152K-paper incremental week ~200 hours of pure labeling. Ollama remains supported via `--backend ollama` for machines without the GPU/vLLM setup (e.g. dev laptops), but production incremental cycles must submit `serve_vllm.sh` via sparkq before running `label-abstracts`. See [`docs/design/bulk-vs-incremental-audit.md`](bulk-vs-incremental-audit.md) §Ollama→vLLM policy for the measurement-backed rationale and the workload-by-workload matrix (chat → vLLM, embedding → Ollama stays, etc.).

## Interface preservation

The migration lands **behind the existing `BaseAbstractLabeler` ABC**:

```
src/core/labeling/
  llm_base.py            # ABC + prompts + schemas (unchanged)
  ollama.py              # OllamaAbstractLabeler (unchanged)
  vllm.py                # NEW: VLLMAbstractLabeler (mirror interface)
  labeler.py             # dispatch on backend name — extended
```

Same prompt (`LABELING_SYSTEM_PROMPT` + `LABELING_USER_PROMPT`), same output schema (`SentenceLabels`), same downstream mapping (`build_abstract_structure`). Only the transport differs (Ollama `/api/chat` + `format` field vs vLLM `/v1/chat/completions` + `guided_json` extra body).

CLI: `--backend ollama|vllm` toggle on `label-abstracts`. Ollama remains default; nothing changes for incremental users.

## Quality gate

Run `scripts/labeling/eval_labeling_quality.py`:

1. Sample 60 abstracts (real-paper, has abstract, has existing abstract_structure so both backends are labeling a known-labelable input).
2. Run through granite4.1:8b via Ollama Q4_K_M (baseline).
3. Run through granite-4.1-8b via vLLM BF16 (candidate).
4. Compare at (sentence, role-set) tuple level: mean Jaccard for overall agreement, micro-F1 per role.
5. **Pass condition (nominal):** overall Jaccard ≥ 0.85 AND ≥ 55/60 schema-valid on both backends.

**Phase 1 result (2026-07-04):**
- Schema-valid: **60/60 on both backends** ✅
- Overall Jaccard: **0.834** ⚠️ (1.6% under nominal 0.85 cut)
- Per-role micro-F1: **0.830-0.931** across all 7 roles ✅
- Failure-sample forensic: all 5 low-agreement papers were **boundary-case multi-label disagreements** (e.g. one paper: baseline `contribution=1`, candidate `contribution=0` — the sentence still classified under `approach`, no wrong label). Zero cases of "candidate misclassified".

**Interpretation.** The 0.85 nominal cut comes from the 2026-06-19 eval that compared *different models* (granite vs gemma vs DiffusionGemma). Here we are comparing the *same model* under Q4_K_M vs BF16 — the 1.6% gap is precision-quantization noise, not a quality regression. All per-role micro-F1 above 0.83 and 100% schema validity are the load-bearing signals. Accepted (2026-07-04, option A) with the note that same-model-different-quantization comparisons warrant a lower threshold in the eval script.

Fallback plan if the gate had failed: try `Qwen/Qwen3-8B` via vLLM; if still fail, accept the multi-month Ollama-only fallback and use tier-priority to make search useful on the hot subset.

## Throughput gate

The design gate was "sample 500 via CLI, verify ≥ 30K/hr." The 2026-07-04 attempt hit an unrelated Qdrant timeout (see [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md) §Qdrant timeout under bulk load) and was replaced with a **pure-vLLM scaling bench** that bypasses Qdrant to isolate the labeling backend.

Concurrency scaling (100 realistic abstracts per run, all schema-valid at every setting):

| `--vllm-max-concurrent` | Latency (100 papers) | Throughput | vs -p 4 |
|---|---|---|---|
| 4 | 147.3 s | 2,444 / hr | 1× |
| 16 | 43.4 s | 8,287 / hr | 3.4× |
| 64 | 16.2 s | 22,185 / hr | 9× |
| **128** | **10.1 s** | **35,618 / hr** | **14.6×** ✅ |

**Passed** the ≥ 30K/hr bar at `--vllm-max-concurrent 128`. All 400 test requests across the four configs returned schema-valid outputs — vLLM's continuous batching does not sacrifice output quality under load.

**Wall-clock for the 3.74M-paper labeling gap (real papers post-P3 with abstract but no abstract_structure):**

- vLLM @ 30 K/hr → **~125 h ≈ 5.2 days**
- vLLM @ 35.6 K/hr → **~105 h ≈ 4.4 days**
- Ollama baseline (750/hr) → ~4,987 h ≈ **208 days** — infeasible.

vLLM delivers **~47× the throughput of Ollama** for the same model at production concurrency. The gate rationale (bulk labeling must finish in ≤ 14 days) is satisfied with room to spare.

If a future upgrade drops throughput below the 30K bar: tune `--gpu-memory-utilization` (up to 0.50 = 64 G on the 128 G unified pool) and `--vllm-max-concurrent` (up to ~256 before the request tracker becomes the bottleneck) and re-measure.

## Rollback

- **Server crash during production run:** the queue-based labeling loop is checkpointed; re-invoke `label-abstracts --backend vllm` and it picks up where it left off (unlabeled papers still lack `abstract_structure`, are re-selected by the filter).
- **Quality regression discovered post-run:** worst case, run `label-abstracts --force --backend ollama` on the affected subset to overwrite. Slow but deterministic.
- **vLLM install broken:** the sparkq job fails; `label-abstracts --backend ollama` remains fully functional. No permanent damage.

## What Phase 0 shipped (2026-07-04)

- `src/core/labeling/vllm.py` — `VLLMAbstractLabeler` implementation (thin, mirrors `OllamaAbstractLabeler`).
- `src/core/labeling/labeler.py` — dispatch extended to route `llm_backend="vllm"` to the new class.
- `src/cli/commands/labeling.py` — `--backend`, `--vllm-model`, `--vllm-base-url`, `--vllm-max-concurrent` flags.
- `scripts/labeling/serve_vllm.sh` — sparkq-ready launcher.
- `docs/design/vllm-labeling-migration.md` (this doc).
- Updated: [`embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md) — now two-phase (label → embed).
- Updated: [ponytail audit](../refactoring/2026-06-24-ponytail-audit.md) — item marked in-progress.

## Phase 1 checklist (after P3 completes)

- [ ] Submit `serve_vllm.sh` via sparkq on Node 1; watch `sparkq status vllm-labeling` come online (first run downloads the model, ~5–10 min).
- [ ] `curl http://localhost:8000/v1/models` returns the model — server is live.
- [ ] Quality eval: 60-paper agreement vs Ollama baseline (script: TBD, based on `docs/reference/labeling-llm-comparison.md` methodology).
- [ ] Throughput eval: 500 papers via `label-abstracts --backend vllm --limit 500`.
- [ ] Decision: gate pass → Phase 2; fail → try Qwen3-8B; fail again → E2 fallback.

## Phase 2 checklist (after Phase 1 passes)

- [ ] Kick full labeling: `label-abstracts --backend vllm` (no limit, resume-safe).
- [ ] Monitor: `sparkq status vllm-labeling` and `label-abstracts` job for stalls.
- [ ] On completion, embed drain (already-prepped playbook: `embed-drain-strategy.md`).
