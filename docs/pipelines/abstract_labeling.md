# Abstract Sentence Labeling Pipeline

## 1. Overview

This document describes the abstract sentence labeling pipeline for papers in the Core Corpus.

### 1.1 Purpose

| Purpose | Description | Example |
|---------|-------------|---------|
| **Rhetorical Classification** | Classify each sentence into structural roles | "We propose X..." → `approach` |
| **Multi-label** | Sentences can belong to multiple roles | "We introduce BERT for NLP" → `approach` + `domain` |
| **Per-sentence Embeddings** | Enable future per-role semantic search | Search only "method" or "result" sentences |
| **Structured Abstracts** | Convert free-text abstracts to structured data | 7-role JSON output |

### 1.2 Rhetorical Roles

| Role | Description | Example Sentence |
|------|-------------|------------------|
| `task` | Problem being addressed or objective | "This paper addresses the challenge of..." |
| `domain` | Application area or research field | "...in the field of natural language processing..." |
| `background` | Prior work, limitations, motivation | "Previous methods suffer from..." |
| `approach` | Key idea, novelty, proposed solution | "We propose a novel architecture that..." |
| `method` | Implementation details, architecture | "The model consists of a transformer encoder..." |
| `result` | Experiments, scores, datasets, findings | "Our method achieves 95.2% accuracy on GLUE..." |
| `contribution` | Contribution claims, impact summary | "Our main contributions are..." |

---

## 2. CLI Commands

### 2.1 Label Abstracts

**Backend selection** (Path B, 2026-07-04):

| Backend | When | Why |
|---|---|---|
| `--backend vllm` (**production default**) | Any run >5K papers | 30K+ papers/hr via continuous batching; the only feasible option at bootstrap scale. Requires the vLLM server up — see [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md). |
| `--backend ollama` (fallback) | Dev laptop, ad-hoc <500 papers | 750 papers/hr serial. Works without a GPU labeling server. |

```bash
# Production default — vLLM backend (server must be running)
uv run python -m src.cli.core_collect label-abstracts --backend vllm

# Dry run
uv run python -m src.cli.core_collect label-abstracts --backend vllm --dry-run --limit 5

# Label a bounded batch
uv run python -m src.cli.core_collect label-abstracts --backend vllm --limit 100

# Re-label everything (overwrite existing abstract_structure)
uv run python -m src.cli.core_collect label-abstracts --backend vllm --force --limit 50

# Fallback: Ollama (dev use, small volumes)
uv run python -m src.cli.core_collect label-abstracts --backend ollama --dry-run --limit 5
```

Gemini backend was removed in v0.12 (2026-06). If you find references to `--llm-backend gemini` in older docs or scripts, they are historical.

---

## 3. Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     Abstract Labeling Pipeline                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────┐  │
│  │  Qdrant  │──▶│ Preprocess & │──▶│ LLM Labels  │──▶│ Map indices  │  │
│  │ (papers) │   │ pysbd split  │   │ by index    │   │ → sentences  │  │
│  └──────────┘   └──────────────┘   └──────┬──────┘   └──────┬───────┘  │
│                                            │ failure          │ success  │
│                                            ▼                  ▼          │
│                                       return None    ┌──────────────┐   │
│                                     (paper skipped)  │ Update Qdrant│   │
│                                                      │ abstract_    │   │
│                                                      │  structure   │   │
│                                                      └──────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Index-Based Approach

The pipeline uses **deterministic sentence splitting** with pysbd, then sends numbered sentences to the LLM which returns only index-based label assignments. This guarantees verbatim sentence fidelity.

```
Step 1: Preprocess     → Replace literal \n, collapse whitespace
Step 2: pysbd split    → Deterministic sentence boundaries
Step 3: Number         → [0] First sentence. [1] Second sentence. ...
Step 4: LLM classify   → Title + full abstract (context) + numbered sentences
Step 5: Map back       → Index → verbatim sentence → role assignments
```

The LLM receives both the **full abstract** (for context) and the **numbered sentences** (for classification). This ensures the LLM understands sentence relationships (e.g., enumerated contributions like "a)... b)... c)...") while only returning lightweight index→label mappings.

### 3.2 Preprocessing

Abstracts from arXiv often contain literal `\n` (backslash-n as two characters) from line wrapping. The pipeline normalizes these before splitting:

```python
clean = abstract.replace("\\n", " ")        # Literal \n from arXiv
clean = re.sub(r"\s+", " ", clean).strip()   # Collapse all whitespace
```

### 3.3 vLLM Backend (production)

- Uses `httpx.AsyncClient` POST to `/v1/chat/completions` (OpenAI-compatible).
- Constrained JSON via the `guided_json` extra-body param → the same `SentenceLabels` Pydantic schema Ollama enforces via `format`.
- Default model: `ibm-granite/granite-4.1-8b` (chosen for family-equivalence with the Ollama default so quality drift is minimized — see [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) §Quality gate).
- Concurrency: **64 in-flight requests by default** — vLLM's continuous batching means high `max_concurrent` is a *feature*, not an OOM risk.
- Throughput: **~30,000+ papers/hr** on GB10 (design target; verified per-corpus at production start).
- Serving: `scripts/labeling/serve_vllm.sh` via sparkq. Operations runbook: [`docs/runbooks/vllm-labeling.md`](../runbooks/vllm-labeling.md).

### 3.4 Ollama Backend (fallback)

- Uses `httpx.AsyncClient` POST to `/api/chat`.
- Passes `format=SentenceLabels.model_json_schema()`.
- Default model: `granite4.1:8b` (selected by the 2026-06-19 60-paper eval — see [`docs/reference/labeling-llm-comparison.md`](../reference/labeling-llm-comparison.md)).
- Concurrency: **1 effective** (Ollama serializes chat requests on the single GPU regardless of client-side `max_concurrent`; measured 2026-07-04: `-p 1` = `-p 8` = 750 papers/hr).
- Timeout: 180s (configurable via `--ollama-timeout`).
- Retry with exponential backoff (max 5 attempts).
- **Use only for dev / ad-hoc small batches** — production incremental cycles at scale must use vLLM per the [`bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) policy.

---

## 4. Structured Output

### 4.1 Pydantic Models

**LLM response** — index-based label assignments:

```python
class SentenceLabel(BaseModel):
    index: int           # Sentence index (0-based)
    labels: list[str]    # Rhetorical roles for this sentence

class SentenceLabels(BaseModel):
    labels: list[SentenceLabel]
```

**Stored output** — verbatim sentences mapped to roles:

```python
class AbstractStructure(BaseModel):
    task: list[str]          # Problem/objective sentences
    domain: list[str]        # Application area sentences
    background: list[str]    # Prior work, limitations, motivation
    approach: list[str]      # Key idea, novelty
    method: list[str]        # Implementation, architecture
    result: list[str]        # Dataset, experiment, scores, ablation
    contribution: list[str]  # Contribution claims

    def to_dict(self) -> dict[str, list[str]]:
        return self.model_dump()
```

### 4.2 LLM Prompt

The user prompt sends title, full abstract (for context), and numbered sentences:

```
Classify each sentence by index into rhetorical roles.

Title: Attention Is All You Need

Full abstract (for context):
The dominant sequence transduction models are based on complex ...

Sentences to classify:
[0] The dominant sequence transduction models are based on complex ...
[1] We propose a new simple network architecture, the Transformer, ...

Return JSON with a "labels" array where each item has "index" (int) and "labels" (list of role strings).
```

### 4.3 Example Output

For a paper titled "Attention Is All You Need":

```json
{
  "task": ["We propose a new simple network architecture, the Transformer, based solely on attention mechanisms."],
  "domain": [],
  "background": ["The dominant sequence transduction models are based on complex recurrent or convolutional neural networks."],
  "approach": ["We propose a new simple network architecture, the Transformer, based solely on attention mechanisms."],
  "method": ["The Transformer uses multi-head self-attention to compute representations of its input and output."],
  "result": ["On two machine translation tasks, these models achieve 28.4 BLEU on the WMT 2014 English-to-German translation task."],
  "contribution": ["Our model achieves 28.4 BLEU on WMT 2014 English-to-German, improving over the existing best results."]
}
```

Note: Sentences can appear in multiple roles (multi-label classification). All sentences are verbatim from pysbd splitting — the LLM never generates sentence text.

---

## 5. Source Tracking

### 5.1 Source Values

| Source Value | Meaning |
|-------------|---------|
| `"vllm"` | vLLM chat completion via `guided_json` (production default) |
| `"ollama"` | Ollama LLM labeling |
| `"none"` | Labeling failed |

### 5.2 Qdrant Payload Fields

```json
{
  "abstract_structure": {
    "task": ["..."],
    "domain": ["..."],
    "background": ["..."],
    "approach": ["..."],
    "method": ["..."],
    "result": ["..."],
    "contribution": ["..."]
  },
  "abstract_structure_source": "vllm"
}
```

---

## 6. CLI Options Reference

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | off | Preview without saving |
| `--limit N` | all | Process max N papers |
| `--batch-size N` | 500 | Papers per batch |
| `--force` | off | Re-label papers with existing abstract_structure |
| `--backend` | `ollama` | LLM backend: `ollama` (fallback) or `vllm` (production default at scale) |
| `--ollama-model` | `granite4.1:8b` | Ollama model (kept for legacy fallback runs) |
| `--ollama-timeout` | `180` | Ollama request timeout in seconds |
| `--vllm-model` | `ibm-granite/granite-4.1-8b` | Model repo name; must match `vllm serve <model>` argument |
| `--vllm-base-url` | `http://localhost:8000` | vLLM OpenAI-compatible endpoint |
| `--vllm-max-concurrent` | `64` | Concurrent in-flight requests to vLLM |

---

## 7. Environment Variables

| Variable | Description |
|----------|-------------|
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |
| `HF_HOME` | HuggingFace cache root — set to `/mnt/nfs/ssd1/huggingface_cache` when serving vLLM |

The Gemini backend was removed in v0.12 (2026-06); `GEMINI_API_KEYS` / `GOOGLE_API_KEY` are no longer read.

---

## 8. Module Structure

```
src/core/labeling/
├── __init__.py          # Module exports (AbstractLabeler, AbstractStructure)
├── llm_base.py          # SentenceLabel/SentenceLabels/AbstractStructure models,
│                        #   prompts, format_numbered_sentences(),
│                        #   build_abstract_structure(), BaseAbstractLabeler ABC
├── ollama.py            # OllamaAbstractLabeler (httpx REST API, granite4.1:8b)
├── vllm.py              # VLLMAbstractLabeler (OpenAI-compatible + guided_json)
└── labeler.py           # AbstractLabeler orchestrator (pysbd split + LLM + mapping)
```

---

## 9. Related Documents

- [Keyword Extraction](./keyword_extraction.md) - Keyword extraction pipeline (similar pattern)
- [Data Model](../architecture/data_model.md) - Qdrant schema details
- [Search Pipeline](./search.md) - How structured abstracts can enhance search
