# Open-Source LLM Migration (remove Gemini, Ollama-only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all closed-source Gemini usage from the labeling and keyword subsystems, making local Ollama (`qwen3.5:27b`) the only LLM backend, and verify the pipeline runs with zero closed-source credentials.

**Architecture:** Both subsystems already have Ollama backends. This deletes the Gemini backend files, removes the `gemini` dispatch branches + params + CLI options, drops the `google-genai` dependency and `GEMINI_*` config, and updates tests to the Ollama-only surface.

**Tech Stack:** Python 3.12, uv, Ollama (`qwen3.5:27b`, installed), pytest. Tests: `uv run --extra dev pytest`.

**Scope note:** Implements `docs/superpowers/specs/2026-06-18-open-source-llm-migration-design.md`. Active model `qwen3.5:27b` (latest installed Qwen); documented fallback Gemma 4 (`ollama pull` to use). Embeddings + search LLM helpers are already Ollama (untouched). `.env` `GEMINI_API_KEYS` left in place but unused.

---

## Conventions (every task)
- Test command: `uv run --extra dev pytest <args>` (pytest is in the `dev` extra).
- This is a removal/refactor: update the test expectations to Ollama-only FIRST, run (see failures), make the source change, run (pass). Commit per task.
- Commits: `git commit --author="rabqatab <minhan.nick.cho@gmail.com>" -m "..."`. NEVER add `Co-Authored-By` / "Generated with Claude Code". Verify `git log -1 --format="%B" | grep -i "co-authored"` empty. `tests/` is NOT gitignored.

## Verified removal surface (2026-06-18 grounding)
- **Labeling:** `src/core/labeling/labeler.py` `AbstractLabeler.__init__(llm_backend="gemini", ollama_model="llama3.1:8b", gemini_model=..., ollama_timeout)`; `_ensure_llm_labeler` branches gemini/ollama. `src/core/labeling/gemini.py` defines `GeminiAbstractLabeler` (delete). CLI `src/cli/commands/labeling.py` has `--llm-backend` (Choice gemini/ollama, default gemini), `--gemini-model`, `--ollama-model` (default llama3.1:8b). `src/core/pipeline/stages.py::label_abstracts_stage(..., llm_backend="gemini")` passes it to `AbstractLabeler`.
- **Keyword:** `src/core/keyword/extractor.py` `__init__(..., llm_backend="gemini", judge_backend=None, ollama_model="llama3.1:8b", gemini_model=..., ...)`; `_ensure_llm_extractor` branches; judge via `judge_backend`. `src/core/keyword/gemini.py` defines `GeminiKeywordExtractor` + `GeminiJudge` (delete). CLI `src/cli/commands/keywords.py` has `--llm` flag, `--llm-backend` (default gemini), `--judge`, `--judge-backend`, `--ollama-model` (default llama3.1:8b).
- **Config:** `src/core/constants.py` — `GEMINI_API_KEYS_ENV`, `GEMINI_API_KEY_ENV`, `get_gemini_api_key()`, `get_gemini_api_keys()`. These are used ONLY by the gemini.py files (confirmed: no other refs) → safe to remove after deletion.
- **Dep:** `google-genai>=1.61.0` in `pyproject.toml`.
- **`__init__.py`:** `src/core/labeling/__init__.py` + `src/core/keyword/__init__.py` mention Gemini only in docstrings (no exports).
- **Tests:** `tests/test_abstract_labeling.py`, `tests/test_llm_keyword_extraction.py` (incl. a `TestGeminiExtraction` class importing `GeminiKeywordExtractor`, and many `llm_backend="gemini"` / `gemini_model` / `"gemini" in source` assertions), and `tests/core/test_pipeline_stages.py:97` (a mock returns source `"gemini"`).
- **Model:** `qwen3.5:27b` confirmed installed in Ollama.

---

## Task 1: Labeling → Ollama-only

**Files:** Modify `src/core/labeling/labeler.py`, `src/cli/commands/labeling.py`, `src/core/pipeline/stages.py`, `src/core/labeling/__init__.py`; Delete `src/core/labeling/gemini.py`; Test: `tests/test_abstract_labeling.py`, `tests/core/test_pipeline_stages.py`.

- [ ] **Step 1: Update tests to the Ollama-only surface (expect failures).**
  - In `tests/test_abstract_labeling.py`: read it; remove/rewrite any test that references `gemini`, `GeminiAbstractLabeler`, or `gemini_model` (delete Gemini-only tests; change `llm_backend="gemini"` → `"ollama"`; drop `gemini_model=` kwargs; any `AbstractLabeler()` default-backend assertion should expect `"ollama"`). Keep/extend the Ollama-path tests.
  - In `tests/core/test_pipeline_stages.py` line ~97: change the mock `labeler.label_abstract.return_value = ({"task": "x"}, "gemini")` → `({"task": "x"}, "ollama")`.
  - Run `uv run --extra dev pytest tests/test_abstract_labeling.py tests/core/test_pipeline_stages.py -q` → expect failures (gemini import / defaults).

- [ ] **Step 2: Make `AbstractLabeler` Ollama-only.** In `src/core/labeling/labeler.py`:
  - `__init__`: drop `gemini_model`; set defaults `llm_backend: str = "ollama"`, `ollama_model: str = "qwen3.5:27b"`. Keep `llm_backend` param for API stability.
  - `_ensure_llm_labeler`: remove the gemini branch + import. Result:
```python
    def _ensure_llm_labeler(self) -> "BaseAbstractLabeler | None":
        if self._llm_labeler is not None:
            return self._llm_labeler
        try:
            if self.llm_backend == "ollama":
                from src.core.labeling.ollama import OllamaAbstractLabeler
                self._llm_labeler = OllamaAbstractLabeler(
                    model=self.ollama_model, timeout=self.ollama_timeout
                )
            else:
                logger.warning(
                    f"Unsupported LLM backend '{self.llm_backend}' (only 'ollama' is supported)"
                )
                return None
            logger.info(f"Abstract labeler initialized ({self.llm_backend})")
        except Exception as e:
            logger.warning(f"Failed to initialize abstract labeler: {e}")
            return None
        return self._llm_labeler
```
  - Remove the `self.gemini_model = ...` assignment.

- [ ] **Step 3: Delete the Gemini labeler.** `git rm src/core/labeling/gemini.py`. Update `src/core/labeling/__init__.py` docstring ("via Gemini or Ollama" → "via Ollama").

- [ ] **Step 4: Update the CLI.** In `src/cli/commands/labeling.py`: remove the `--llm-backend` and `--gemini-model` options; change `--ollama-model` default to `"qwen3.5:27b"`. Remove `llm_backend` and `gemini_model` from the command function signature and from the `AbstractLabeler(...)` call (pass only `ollama_model`/`ollama_timeout`; `AbstractLabeler` now defaults `llm_backend="ollama"`). Update the docstring/examples that mention gemini. Update the `_run_labeling_loop`/`_label_abstracts_async` helper signatures accordingly (drop the gemini params).

- [ ] **Step 5: Update the stage.** In `src/core/pipeline/stages.py::label_abstracts_stage`: change the default `llm_backend="gemini"` → `llm_backend="ollama"` (it passes through to `AbstractLabeler`). Confirm `tests/core/test_pipeline_stages.py::test_label_abstracts_stage_returns_counts` still passes (it mocks `AbstractLabeler`).

- [ ] **Step 6: Run tests.** `uv run --extra dev pytest tests/test_abstract_labeling.py tests/core/test_pipeline_stages.py -q` → pass. Smoke: `env -u GEMINI_API_KEYS uv run python -m src.cli.core_collect label-abstracts --help` → no `--llm-backend`/`--gemini-model`; `--ollama-model` default qwen3.5:27b; exit 0.

- [ ] **Step 7: Commit** (`feat(labeling): Ollama-only (qwen3.5:27b); remove Gemini backend`).

---

## Task 2: Keyword → Ollama-only

**Files:** Modify `src/core/keyword/extractor.py`, `src/cli/commands/keywords.py`, `src/core/keyword/__init__.py` (+ `judge.py` if it imports gemini); Delete `src/core/keyword/gemini.py`; Test: `tests/test_llm_keyword_extraction.py`.

- [ ] **Step 1: Update tests to Ollama-only (expect failures).** In `tests/test_llm_keyword_extraction.py`:
  - Delete the `TestGeminiExtraction` class and `test_gemini_extract_keywords` (they import `GeminiKeywordExtractor`).
  - Change every `llm_backend="gemini"` → `llm_backend="ollama"`; drop `gemini_model=` kwargs; change assertions like `assert ext.llm_backend == "gemini"` / `assert "gemini" in source` / `assert ext.gemini_model == ...` to the Ollama equivalents (e.g. `"ollama"`, and remove gemini_model assertions). For `assert "gemini" not in source` keep as-is (still true). Keep the `judge_backend` tests but use `"ollama"`.
  - Run `uv run --extra dev pytest tests/test_llm_keyword_extraction.py -q` → expect failures.

- [ ] **Step 2: Make `KeywordExtractor` Ollama-only.** In `src/core/keyword/extractor.py`:
  - `__init__`: drop `gemini_model`; defaults `llm_backend: str = "ollama"`, `ollama_model: str = "qwen3.5:27b"`; `judge_backend` default stays `None` (→ falls back to `llm_backend`).
  - `_ensure_llm_extractor`: remove gemini branch + import; keep only the ollama branch (mirror Task 1's pattern: `if self.llm_backend == "ollama": from src.core.keyword.ollama import OllamaKeywordExtractor; ...` else warn+return None).
  - Find where the judge backend is built (the `KeywordJudge`/`_ensure_judge`): remove the gemini branch there too; ollama-only. Read `extractor.py` + `judge.py` to locate it.
  - Remove `self.gemini_model` assignment.

- [ ] **Step 3: Delete the Gemini keyword backend.** `git rm src/core/keyword/gemini.py`. Update `src/core/keyword/__init__.py` docstring ("via Gemini or Ollama" → "via Ollama").

- [ ] **Step 4: Update the CLI.** In `src/cli/commands/keywords.py`: remove `--llm-backend` and `--judge-backend` options (LLM/judge are Ollama-only now); keep `--llm`/`--judge` flags; change `--ollama-model` default → `"qwen3.5:27b"`. Update the command function signature + the `KeywordExtractor(...)` construction (drop `llm_backend`/`judge_backend`/`gemini_model` args, or pass `llm_backend="ollama"`). Update help/examples.

- [ ] **Step 5: Run tests + smoke.** `uv run --extra dev pytest tests/test_llm_keyword_extraction.py -q` → pass. `env -u GEMINI_API_KEYS uv run python -m src.cli.core_collect extract-keywords --help` → no gemini options; exit 0.

- [ ] **Step 6: Commit** (`feat(keyword): Ollama-only (qwen3.5:27b); remove Gemini backend`).

---

## Task 3: Remove Gemini config + dependency

**Files:** Modify `src/core/constants.py`, `pyproject.toml` (+ `uv.lock`).

- [ ] **Step 1: Remove Gemini config.** In `src/core/constants.py`: delete `GEMINI_API_KEYS_ENV`, `GEMINI_API_KEY_ENV`, `get_gemini_api_key()`, `get_gemini_api_keys()` (and any `DEFAULT_*GEMINI*` model constants). First `grep -rn "get_gemini_api_key\|GEMINI_API_KEY\|GEMINI_API_KEYS\|gemini" src/ | grep -v __pycache__` to confirm no remaining references after Tasks 1–2 (should be none in code; only docstrings/`.env`). If any remain, fix them.

- [ ] **Step 2: Remove the dependency.** Run `uv remove google-genai` (updates `pyproject.toml` + `uv.lock`). Verify it's gone: `grep -i "google-genai\|google_genai" pyproject.toml` → nothing.

- [ ] **Step 3: Confirm the import is gone.** `uv run python -c "import google.genai" 2>&1 | tail -1` → ModuleNotFoundError (the package is uninstalled). And `uv run python -c "import src.core.constants, src.core.labeling.labeler, src.core.keyword.extractor; print('imports ok')"` → ok (no dangling gemini imports).

- [ ] **Step 4: Commit** (`build: drop google-genai dep + Gemini config (Ollama-only LLMs)`).

---

## Task 4: Zero-closed-source verification

**Files:** none.

- [ ] **Step 1: No Gemini in code.** `grep -rinE "genai|gemini|google-genai|google\.generativeai" src/ | grep -v __pycache__` → only `src/core/enrichment/acm_browser.py` (the benign `ChatGPT-User`/`Google-Extended` user-agent comment). If anything else appears, fix it.

- [ ] **Step 2: Runs with no credentials.** With `GEMINI_API_KEYS` unset and Ollama up:
```bash
env -u GEMINI_API_KEYS -u GEMINI_API_KEY -u GOOGLE_API_KEY \
  uv run python -m src.cli.core_collect label-abstracts --dry-run --limit 1
env -u GEMINI_API_KEYS -u GEMINI_API_KEY -u GOOGLE_API_KEY \
  uv run python -m src.cli.core_collect extract-keywords --llm --dry-run --limit 1
```
Both exit 0, no credential errors, no `import google` error. (Dry-run counts; if `--limit`/`--dry-run` combos differ for these commands, use the smallest real-work invocation — the point is the Ollama LLM path initializes without Gemini.)

- [ ] **Step 3: Full suites + orchestration.**
`uv run --extra dev pytest tests/ -q` → green (or at least the labeling/keyword/pipeline suites; note any pre-existing unrelated failures).
`uv run dagster definitions validate -m src.orchestration.definitions` → "Validation successful" (labeling/keyword feed the assets).

- [ ] **Step 4: Commit any fixups** (`chore(llm): open-source migration verification`).

---

## Self-Review
- **Spec coverage:** labeling Ollama-only + delete gemini.py (Task 1); keyword Ollama-only + delete gemini.py (Task 2); constants + google-genai dep removed (Task 3); zero-closed-source verification incl. running with `GEMINI_API_KEYS` unset (Task 4). Model `qwen3.5:27b` set as the default everywhere; Gemma 4 fallback is documentation-only (spec), no code needed. Embeddings/search untouched (already Ollama).
- **Placeholder scan:** complete code for the load-bearing `_ensure_llm_labeler` rewrite; the test-update and CLI-option-removal steps are precise directives over an enumerated, grounded surface (exact files/symbols/lines), not vague "handle it". The "read the file" notes are to locate the exact judge-dispatch site, consistent with prior plans.
- **Type consistency:** `AbstractLabeler(llm_backend="ollama", ollama_model="qwen3.5:27b", ollama_timeout=...)` and `KeywordExtractor(..., llm_backend="ollama", ollama_model="qwen3.5:27b", ...)` — `gemini_model` removed from both; `label_abstracts_stage(llm_backend="ollama")` matches. CLI options reduced to `--ollama-model`/`--ollama-timeout` (+ `--llm`/`--judge` flags for keyword). No symbol references a deleted `gemini.py`.

## Out of scope → follow-ups
- `ollama pull <gemma4-tag>` if/when the Gemma 4 fallback is actually wanted.
- Tuning `qwen3.5:27b` throughput for the full-corpus labeling backlog (27b is slower than the prior gemini-flash; consider a smaller Qwen for bulk if throughput becomes the constraint).
- Removing the unused `GEMINI_API_KEYS` line from `.env` (left in place; harmless).
