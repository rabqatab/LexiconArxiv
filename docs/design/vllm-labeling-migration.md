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

**Serve via sparkq**, single-node:

```bash
sparkq submit "./scripts/labeling/serve_vllm.sh" \
    --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
    --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key vllm-labeling-2026-07-04 --json
```

sparkq's real-memory admission gate rounds up the vLLM footprint from `--gpu-memory-utilization 0.30` × 128 G = 38 G automatically. Declaring `--gpu-mem 40G` lets the dry-run fit check match the auto-raised number.

Client-side: `label-abstracts --backend vllm --vllm-base-url http://localhost:8000`.

**Not systemd** — the load is bootstrap-shaped, not steady-state. After bootstrap, incremental labeling (~5K papers/week) is small enough that Ollama's serial throughput is fine, and running two labeling backends indefinitely is complexity we don't need.

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

**Before running against production**, we run the same 60-paper eval that selected granite4.1:8b in 2026-06-19:

1. Sample 60 abstracts (same set used in the original eval — reproducibility).
2. Run through granite4.1:8b via Ollama (baseline).
3. Run through granite-4.1-8b via vLLM (candidate).
4. Compare label agreement at the (sentence, role) tuple level.
5. **Pass condition:** agreement ≥ 85% AND no schema-invalid outputs.

If pass: proceed to production. If fail: try Qwen3-8B on vLLM; if still fail, fall back to running the whole thing on Ollama with priority-tier filtering and accepting a multi-month labeling window.

## Throughput gate

Immediately after quality passes:

1. Sample 500 papers, run through vLLM at `--vllm-max-concurrent 64`.
2. Report throughput in papers/hr.
3. **Pass condition:** ≥ 30,000 papers/hr.

Anecdotal reports for 8B-class models on batched inference put the ceiling around 100K–300K papers/hr for constrained JSON at modest sequence lengths (labeling prompts are ~500 tokens in, ~200 out). 30K/hr is a conservative acceptance bar.

If throughput is below 30K/hr but agreement is good: tune `--gpu-memory-utilization` (up to 0.50 = 64 G) and `--vllm-max-concurrent` (up to 128) and re-measure. Only fall back to Ollama if the tuned throughput still can't finish 3M papers in ≤ 14 days.

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
