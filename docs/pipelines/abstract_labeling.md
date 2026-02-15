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

```bash
# Dry run with Gemini (default)
uv run python -m src.cli.core_collect label-abstracts --dry-run --limit 5

# Dry run with Ollama (local)
uv run python -m src.cli.core_collect label-abstracts --llm-backend ollama --dry-run --limit 5

# Label all unlabeled papers
uv run python -m src.cli.core_collect label-abstracts --limit 100

# Re-label all papers (overwrite existing)
uv run python -m src.cli.core_collect label-abstracts --force --limit 50

# Custom model
uv run python -m src.cli.core_collect label-abstracts --gemini-model gemini-2.5-pro
```

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

### 3.3 Gemini Backend

- Uses `google-genai` SDK with `response_schema=SentenceLabels`
- Structured JSON output via `response_mime_type="application/json"`
- Default model: `gemini-2.0-flash`
- Supports multiple API keys (comma-separated) for round-robin rotation
- Rate limiting: `asyncio.Semaphore` (max_concurrent=5) + configurable delay
- Retry with exponential backoff (max 5 attempts)
- Temperature: 0.1

### 3.4 Ollama Backend

- Uses `httpx.AsyncClient` POST to `/api/chat`
- Passes `format=SentenceLabels.model_json_schema()`
- Default model: `llama3.1:8b`
- Concurrency: 1 (local model)
- Timeout: 180s (configurable via `--ollama-timeout`)
- Retry with exponential backoff (max 5 attempts)

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
| `"gemini"` | Gemini LLM labeling |
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
  "abstract_structure_source": "gemini"
}
```

---

## 6. CLI Options Reference

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | off | Preview without saving |
| `--limit N` | all | Process max N papers |
| `--batch-size N` | 100 | Papers per batch |
| `--force` | off | Re-label papers with existing abstract_structure |
| `--llm-backend` | `gemini` | LLM backend: `gemini` or `ollama` |
| `--gemini-model` | `gemini-2.0-flash` | Gemini model name |
| `--ollama-model` | `llama3.1:8b` | Ollama model name |
| `--ollama-timeout` | `180` | Ollama request timeout in seconds |

---

## 7. Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Gemini API key(s), comma-separated for round-robin (required for `--llm-backend gemini`) |
| `GOOGLE_API_KEY` | Alternative to `GEMINI_API_KEY` |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |

---

## 8. Module Structure

```
src/core/labeling/
├── __init__.py          # Module exports (AbstractLabeler, AbstractStructure)
├── llm_base.py          # SentenceLabel/SentenceLabels/AbstractStructure models,
│                        #   prompts, format_numbered_sentences(),
│                        #   build_abstract_structure(), BaseAbstractLabeler ABC
├── gemini.py            # GeminiAbstractLabeler (google-genai SDK, round-robin)
├── ollama.py            # OllamaAbstractLabeler (httpx REST API)
└── labeler.py           # AbstractLabeler orchestrator (pysbd split + LLM + mapping)
```

---

## 9. Related Documents

- [Keyword Extraction](./keyword_extraction.md) - Keyword extraction pipeline (similar pattern)
- [Data Model](../architecture/data_model.md) - Qdrant schema details
- [Search Pipeline](./search.md) - How structured abstracts can enhance search
