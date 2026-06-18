# Replace Closed-Source (Gemini) LLM with Open-Source (local Ollama) — Design

**Date:** 2026-06-18
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude Code

## 1. Motivation

The corpus has grown large enough that the closed-source LLM usage (Google **Gemini**, via the `google-genai` SDK) is a cost/throughput/rate-limit liability at scale, and adds an external-credential dependency (`GEMINI_API_KEYS`). All Gemini usage is in two pipeline subsystems — **abstract labeling** and **keyword extraction/judging** — and **both already have working local Ollama backends**. This design fully removes the closed-source path and makes local Ollama the only LLM backend.

Scope confirmed by audit: the only closed-source LLM references in `src/` are Gemini (`google-genai`). There is **no** OpenAI/Anthropic/Cohere usage. (`src/core/enrichment/acm_browser.py` only mentions `ChatGPT-User`/`Google-Extended` in a robots/user-agent comment — not LLM usage.) Embeddings (Ollama `qwen3-embedding:8b`) and search HyDE/RAG-fusion (Ollama via `get_ollama_base_url`) are already open-source and unchanged.

## 2. Model selection

- **Active model:** **`qwen3.5:27b`** — the latest Qwen family model installed in the local Ollama (`qwen2.5` → `qwen3` → `qwen3.5`; no newer Qwen is installed/runnable as of 2026-06-18). Highest local quality, closest to the prior `gemini-3-flash` for structured rhetorical-role labeling; heavier/slower on the shared GB10 than smaller models — an accepted quality-over-throughput tradeoff. Configurable via the existing `--ollama-model` option / a constant.
- **Documented fallback:** **Gemma 4** (e.g. `gemma4:27b`). NOT currently pulled — requires `ollama pull <gemma4-tag>` before use; documentation-only alternative, does not affect the active path. (Prior gemma3:27b is also available if needed.)

## 3. Scope

**In scope (full removal of Gemini):**
- **Labeling** (`src/core/labeling/`): make Ollama the only backend in `AbstractLabeler` (remove the `gemini` branch and the `gemini_model` param; `ollama_model` default → `qwen3.5:27b`). **Delete** `src/core/labeling/gemini.py`. CLI `label-abstracts`: remove `--llm-backend` and `--gemini-model`; keep `--ollama-model` (default `qwen3.5:27b`).
- **Keyword** (`src/core/keyword/`): **delete** `src/core/keyword/gemini.py`; remove Gemini branches/imports from `extractor.py`, `judge.py`, `llm_base.py`; CLI `extract-keywords`: `--llm-backend` / `--judge-backend` become Ollama-only (default `ollama`). The default keyword path remains sync KeyBERT (already open).
- **Config** (`src/core/constants.py`): remove `GEMINI_API_KEYS_ENV`, `get_gemini_api_keys()`, and the Gemini model-name constants.
- **Dependencies:** remove `google-genai` from `pyproject.toml` and update `uv.lock`.
- **Tests:** remove Gemini-specific tests; keep/extend the Ollama-backend tests for labeling and keyword.

**Out of scope (YAGNI):** embeddings and search LLM helpers (already Ollama). The `.env` `GEMINI_API_KEYS` line is left in place but unused (harmless; not edited).

## 4. Verification (zero closed-source guarantee)

The implementation is not complete until ALL of these hold:
1. `grep -rinE "genai|gemini|google-genai|google\.generativeai" src/` returns only the benign `acm_browser.py` user-agent comment (no code/imports/deps).
2. `uv run python -c "import google.genai"` fails (dep removed) — confirming nothing imports it.
3. `label-abstracts` and `extract-keywords --llm` run end-to-end through Ollama **with `GEMINI_API_KEYS` unset** (e.g. `env -u GEMINI_API_KEYS ...`), producing labels/keywords.
4. The labeling + keyword test suites pass; `dagster definitions validate` still passes (labeling/keyword stages are used by the orchestration assets).

## 5. Error handling

The Ollama backends already pre-check model availability (`check_model_available`) and surface a clear error if the model isn't pulled. Pre-flight: `qwen3.5:27b` is confirmed installed. If a future run selects an unpulled model (e.g. the Gemma 4 fallback), the existing check produces an actionable "model not found in Ollama" message.

## 6. Open items (resolve in the implementation plan)
- Exact removal surface in `keyword/extractor.py`, `judge.py`, `llm_base.py` (how the backend is dispatched — confirm whether removing the gemini branch leaves a clean ollama-only path or needs a small refactor).
- Whether `AbstractLabeler` keeps an `llm_backend` param (defaulting/forcing "ollama") for API stability, or drops it entirely; same for the keyword extractor/judge.
- The exact `gemma4` Ollama tag to document once known/pulled.
