# Labeling LLM Comparison & Selection

> **Historical eval — kept for the record.** As of 2026-07-04, **production labeling runs on vLLM + `ibm-granite/granite-4.1-8b`**, not Ollama. This document is the historical basis for choosing the **Granite family**; the vLLM migration reuses the same model family so the family-selection numbers below still apply. Ollama chat is retired from every pipeline stage — the `granite4.1:8b` Ollama path in `label-abstracts` (`--backend ollama`) is preserved as a dev-laptop fallback only. See [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) and [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Ollama→vLLM policy for the current policy.

**Date:** 2026-06-19
**Decision:** the abstract-labeling and keyword LLM is **`granite4.1:8b`** (local Ollama).

This records the head-to-head that picked the labeling model after the
[open-source LLM migration](../superpowers/specs/2026-06-18-open-source-llm-migration-design.md)
removed Gemini. The full experiment harness lives **outside this repo** at
`~/PythonProjects/diffusiongemma-eval/` (kept separate so its 16 GB model and custom
`llama.cpp` build don't weigh on this project).

## Task & metric

Classify each abstract sentence into 7 rhetorical roles
(`task, domain, background, approach, method, result, contribution`).
Accuracy = per-sentence **agreement vs the prior Gemini `abstract_structure` gold**
over 60 corpus abstracts (a high-quality reference, **not** ground truth).

## Results

| model | reliability | accuracy | speed (warm) | |
|---|---|---|---|---|
| **granite4.1:8b** | **100%** | 0.912 | **4.7s** | ✅ **selected** |
| gemma4:e4b | 100% | 0.942 | 19.3s | accurate but 4× slower |
| qwen3.5:9b | 100% | 0.962 | 186s | best accuracy, unusably slow |
| phi4-mini | 100% | 0.868 | 4.6s | |
| llama3.1:8b | 100% | 0.852 | 4.8s | |
| deepseek-r1:7b | 100% | 0.728 | 16.9s | |
| qwen3:8b | 100% | 0.841 | 44.6s | |
| DiffusionGemma 26B-A4B | see below | — | — | not adopted |

All autoregressive Ollama models hit **100% parse reliability** because Ollama's
`format=<schema>` compiles the Pydantic schema to a llama.cpp GBNF grammar and
constrains decoding. `granite4.1:8b` is the best speed/accuracy/reliability balance
and was already wired into `AbstractLabeler`, so adopting it was a one-line default
change.

## DiffusionGemma — evaluated, not adopted

DiffusionGemma (Google discrete-diffusion MoE) was tested because diffusion promises
faster generation. Findings:

- **Constrained JSON decoding is unsupported for diffusion** in llama.cpp — the
  `--json-schema`/`--grammar` flags are no-ops for the diffusion sampler
  (token-grammar masking has no "next token" in parallel block denoising). Free-form
  JSON parsed only **52%** of the time.
- **Speed is actually comparable, not faster** — warm generation ≈ 5.8s (terse) to
  15.8s (thinking); the initial "24s/5× slower" was a cold-model-reload artifact.
  Diffusion's edge needs long outputs; labeling output (~30 tokens) is too short.
- **Schema-free line format** (`index: roles` + lenient parse) fixes reliability only
  with thinking ON (≈100% coverage, 0.962 agree, but 15.8s = 3.4× granite). The fast
  "terse" config is unreliable at scale (n=60: 83% full-parse, 87% coverage, 0.889
  agree — below granite).

**Verdict:** granite dominates the practical frontier (fast + 100% reliable +
integrated + accurate-enough). DiffusionGemma's fast config is unreliable and less
accurate; its reliable config is 3.4× slower and would need a separate non-Ollama
serving stack — not worth it for labeling. It remains a documented R&D track in the
separate eval project, to revisit if constrained decoding lands in a servable diffusion
runtime, or if a long-output task makes diffusion's speed edge real.
