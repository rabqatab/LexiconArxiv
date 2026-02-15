# Keyword Extraction Pipeline

## 1. Overview

This document describes the keyword/acronym extraction pipeline for papers in the Core Corpus.

### 1.1 Purpose

| Purpose | Description | Example |
|---------|-------------|---------|
| **Acronym Extraction** | Extract model/method names from title/abstract | "HyDE: Hypothetical..." → `["HyDE"]` |
| **Semantic Keywords** | Extract key concepts from abstract | "...retrieval augmented generation..." → `["retrieval", "generation"]` |
| **LLM Extraction** | Extract keywords using Gemini or Ollama | "...introduce BERT..." → `["BERT", "language representation"]` |
| **LLM Judge** | Validate and filter keywords for relevance | Remove false positives, keep core terms |
| **Search Quality** | Enable BM25 keyword matching | "give me the HyDE paper" → returns HyDE paper |

### 1.2 Supported Query Types

| Query Type | Example | Solution |
|------------|---------|----------|
| **Exact Paper Search** | "give me the HyDE paper" | Acronym extraction + BM25 matching |
| **Research Trend Search** | "recent research trend of legal IR" | Semantic keywords + Dense embedding |

---

## 2. CLI Commands

### 2.1 Extract Keywords

```bash
# LLM-first extraction with Gemini (primary) + fallback: regex + KeyBERT
uv run python -m src.cli.core_collect extract-keywords --llm --judge

# LLM-first with Ollama (local)
uv run python -m src.cli.core_collect extract-keywords --llm --judge --llm-backend ollama

# LLM-first, fallback: regex only (no KeyBERT)
uv run python -m src.cli.core_collect extract-keywords --llm --judge --no-keybert

# Fallback-only: regex + KeyBERT (no LLM)
uv run python -m src.cli.core_collect extract-keywords

# Regex only (fastest, no model loading)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Better embedding model for KeyBERT fallback
uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

# Preview without saving
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Re-extract for ALL papers (including those with existing keywords)
uv run python -m src.cli.core_collect extract-keywords --force

# Limit number of papers to process
uv run python -m src.cli.core_collect extract-keywords --limit 1000

# Adjust batch size
uv run python -m src.cli.core_collect extract-keywords --batch-size 200
```

### 2.2 View Statistics

```bash
# Show keyword extraction statistics
uv run python -m src.cli.core_collect keyword-stats

# Output as JSON
uv run python -m src.cli.core_collect keyword-stats --json
```

### 2.3 Clear Keywords

```bash
# Clear checkpoint (restart from beginning)
uv run python -m src.cli.core_collect clear-keyword-checkpoint

# Clear all keywords from corpus
uv run python -m src.cli.core_collect clear-keywords --confirm
```

---

## 3. Extraction Behavior

### 3.1 Default Mode (skip existing)

By default, papers that already have keywords are **skipped**:

```bash
uv run python -m src.cli.core_collect extract-keywords
# Only processes papers where keywords = []
```

### 3.2 Force Mode (re-extract all)

With `--force`, all papers are re-processed and keywords are **replaced**:

```bash
uv run python -m src.cli.core_collect extract-keywords --force
# Re-extracts for ALL papers, replacing existing keywords
```

### 3.3 Extraction Modes

| Mode | Command | Description |
|------|---------|-------------|
| **LLM Pipeline (recommended)** | `extract-keywords --llm --judge` | LLM-first + fallback: regex + KeyBERT + Judge |
| **Ollama Pipeline** | `extract-keywords --llm --judge --llm-backend ollama` | Local LLM pipeline |
| **Fallback Only (default)** | `extract-keywords` | Regex + KeyBERT (no LLM) |
| **Regex Only** | `extract-keywords --no-keybert` | Fast, acronyms only |
| **Re-extract** | `extract-keywords --force` | Replace existing keywords |

---

## 4. LLM-First Extraction Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Keyword Extraction Pipeline                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐   ┌──────────────────┐                                │
│  │  Qdrant  │──▶│  LLM Extraction  │──── success ──┐               │
│  │ (papers) │   │ (Gemini/Ollama)  │                │               │
│  └──────────┘   └───────┬──────────┘                │               │
│                         │ failure                    │               │
│                         ▼                            │               │
│               ┌──────────────────┐                   │               │
│               │    Fallback:     │                   │               │
│               │  Regex + KeyBERT │                   │               │
│               └────────┬─────────┘                   │               │
│                        │                             │               │
│                        ▼                             ▼               │
│               ┌─────────────────────────────────────────────┐      │
│               │          Normalize & Deduplicate             │      │
│               └──────────────────┬──────────────────────────┘      │
│                                  │                                  │
│                                  ▼                                  │
│                        ┌──────────────────┐                        │
│                        │   LLM Judge      │                        │
│                        │ (Gemini/Ollama)  │                        │
│                        └────────┬─────────┘                        │
│                                 │                                   │
│                                 ▼                                   │
│                        ┌──────────────────┐                        │
│                        │  Update Qdrant   │                        │
│                        │   (keywords)     │                        │
│                        └──────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘

LLM Extraction:  primary (--llm to enable, always attempted with or without abstract)
Fallback:        regex + KeyBERT (only when LLM fails or is not enabled)
LLM Judge:       optional (--judge to enable)
```

LLM extraction is the primary method. Regex + KeyBERT only run as fallback when LLM produces no results. The Judge filters the final keyword list.

### 4.1 Phase 1: Regex-based Acronym Extraction

Extracts explicit acronyms and model names from title and abstract.

#### Title Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| `ACRONYM: Description` | "BERT: Pre-training of..." | `^([A-Z][A-Za-z0-9\-]{1,10}):\s` |
| `ACRONYM - Description` | "ColBERT - Efficient..." | `^([A-Z][A-Za-z0-9]{1,10})\s*[-–—]\s` |
| `Description (ACRONYM)` | "...Understanding (BERT)" | `\(([A-Z][A-Za-z0-9\-]{1,10})\)\s*$` |
| Inline ACRONYM | "BERT-based Models..." | `\b([A-Z]{2,10}(?:-[A-Z0-9]+)?)\b` (with validation) |
| CamelCase name | "ChatGPT", "FastText", "PyTorch" | `\b([A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+)\b` |

#### Abstract Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| "We propose X" | "We introduce HyDE, a method..." | `(?:introduce\|propose\|present)\s+([A-Z][A-Za-z0-9\-]+)(?:,\|\s+(?:a\|an\|the\|for\|to\|which\|that)\b)` |
| "called X" | "...called BERT..." | `called\s+([A-Z][A-Za-z0-9]+)` |
| "named X" | "...model named GPT-4..." | `named\s+([A-Z][A-Za-z0-9\-]+)` |
| Model version | "GPT-4", "BERT-large", "T5-base" | `\b([A-Z][A-Za-z]*-(?:small\|base\|large\|xl\|xxl\|\d+(?:\.\d+)?[bB]?))\b` |
| "dubbed/termed X" | "...dubbed AlphaFold..." | `(?:dubbed\|termed)\s+([A-Z][A-Za-z0-9\-]+)` |
| "known as X" | "...known as ResNet..." | `(?:known\s+as\|referred\s+to\s+as)\s+([A-Z][A-Za-z0-9\-]+)` |
| ", the Name," | "..., the Transformer, ..." | `,\s+the\s+([A-Z][A-Za-z0-9\-]+)(?:,\|\.\s)` |
| CamelCase name | "ChatGPT", "LangChain" | `\b([A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+)\b` |
| Defined acronym | "...Retrieval-Augmented Generation (RAG)..." | `\(([A-Z]{2,8})\)` |
| Inline acronym | "...using LLMs for..." | `\b([A-Z]{2,10}s?)\b` |

### 4.2 Phase 2: KeyBERT Semantic Extraction

Extracts semantically important keywords from abstract using transformer embeddings.

```python
from keybert import KeyBERT

kw_model = KeyBERT(model="all-MiniLM-L6-v2")  # configurable via --embedding-model

keywords = kw_model.extract_keywords(
    abstract,
    keyphrase_ngram_range=(1, 2),  # 1-2 word phrases
    stop_words='english',
    top_n=5,                        # Top 5 keywords
    use_mmr=True,                   # Maximal Marginal Relevance
    diversity=0.7
)
# Result: [("retrieval augmented", 0.85), ("language model", 0.72), ...]
```

#### KeyBERT Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| `keyphrase_ngram_range` | (1, 2) | 1-2 word keyphrases |
| `top_n` | 5 | Max 5 keywords per paper |
| `use_mmr` | True | Enable diversity |
| `diversity` | 0.7 | Diversity level |
| `min_score` | 0.3 | Minimum confidence threshold |
| `embedding_model` | `all-MiniLM-L6-v2` | Default sentence-transformers model (configurable) |

### 4.3 LLM Keyword Extraction (Primary)

Uses Gemini API or local Ollama to extract structured keywords from title and/or abstract. This is the primary extraction method — always attempted when `--llm` is enabled, even for papers without abstracts (title-only extraction). Includes retry logic with exponential backoff (up to 5 attempts).

**Structured Output** (Pydantic model used as JSON schema):

```python
class ExtractedKeywords(BaseModel):
    task: list[str]              # Specific problem or objective (e.g. 'text classification')
    method: list[str]            # Techniques, algorithms (e.g. 'contrastive learning')
    model: list[str]             # Named models — proper nouns (e.g. 'BERT', 'GPT-4')
    domain: list[str]            # Application area (e.g. 'NLP', 'computer vision')
    dataset: list[str]           # Benchmarks, datasets (e.g. 'GLUE', 'SQuAD')
    contribution_type: list[str] # Kind of contribution (e.g. 'model', 'survey', 'benchmark')
    modality: list[str]          # Data types (e.g. 'text', 'image', 'code', 'multimodal')
```

#### Gemini Backend

- Uses `google-genai` SDK with `response_schema=ExtractedKeywords`
- Structured JSON output via `response_mime_type="application/json"`
- Default model: `gemini-2.0-flash`
- Rate limiting: `asyncio.Semaphore` + configurable delay
- Temperature: 0.1

#### Ollama Backend

- Uses `httpx.AsyncClient` to POST to `/api/chat`
- Passes `format=ExtractedKeywords.model_json_schema()`
- Default model: `llama3.1:8b`
- Default concurrency: 1 (local model)
- Timeout: 180s (configurable via `--ollama-timeout`)

### 4.4 LLM Judge Validation (Optional)

Validates the keyword list by classifying each keyword as relevant or irrelevant.

**Structured Output**:

```python
class JudgeResult(BaseModel):
    relevant: list[str]     # Keywords central to the paper's contribution
    irrelevant: list[str]   # Generic, tangential, or false positive keywords
```

**Fallback behavior**: On failure (API error, timeout), returns all input keywords unchanged.

---

## 5. Filtering & Validation

### 5.1 Stopword List

Common words and meaningless acronyms are filtered. Stopwords are organized into four categories:

```python
# Common English words that may match acronym patterns
COMMON_WORDS = {
    "IT", "IS", "OR", "AN", "AS", "AT", "BE", "BY", "THE", "FOR", "AND",
    "USING", "BASED", "LEARNING", "NEURAL", "NETWORK", "DEEP", "DATA", ...
}

# Section headers and structural terms
SECTION_HEADERS = {
    "INTRODUCTION", "CONCLUSION", "ABSTRACT", "METHODS",
    "RESULTS", "DISCUSSION", "REFERENCES", "BACKGROUND", ...
}

# Generic academic terms
GENERIC_TERMS = {
    "PAPER", "STUDY", "MODEL", "SYSTEM", "APPROACH",
    "FRAMEWORK", "ANALYSIS", "RESEARCH", "SURVEY", ...
}

# Roman numerals and numbering
NUMBERING = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", ...
}

# Combined stopwords set
STOPWORDS = COMMON_WORDS | SECTION_HEADERS | GENERIC_TERMS | NUMBERING
```

### 5.2 Validation Rules

| Rule | Description |
|------|-------------|
| Min length | 2+ characters |
| Max length | 15 characters or less |
| Contains letter | Must contain at least one letter |
| Characters | Letters, numbers, hyphens only |
| Stopwords | Filtered out |
| CamelCase filter | Rejects CamelCase matches where all segments are common English words (filters HTML artifacts) |
| Plural normalization | All-caps plural forms (e.g., "LLMs") also emit the singular ("LLM") |

---

## 6. Source Tracking

### 6.1 Pipe-Delimited Format

The `keywords_source` field uses a pipe-delimited format to track which phases contributed keywords:

| Source Value | Meaning |
|-------------|---------|
| `"gemini"` | Gemini LLM extraction |
| `"gemini\|judge"` | Gemini LLM + judge validation |
| `"ollama\|judge"` | Ollama LLM + judge validation |
| `"regex"` | Regex fallback only |
| `"regex\|keybert"` | Regex + KeyBERT fallback |
| `"regex\|keybert\|judge"` | Fallback + judge |
| `"none"` | No keywords extracted |

When LLM succeeds, regex/KeyBERT do not run (no mixing). Fallback sources only appear when LLM is unavailable or fails.

### 6.2 Qdrant Payload Fields

```json
{
  "keywords": ["BERT", "NLP", "language model"],
  "keywords_source": "gemini|judge"
}
```

### 6.3 Export Format

Keywords can be exported to JSON:

```bash
# Export is done via Python script
uv run python -c "
from src.core.storage import QdrantStorage
import json

storage = QdrantStorage()
# ... scroll and export to data/core/keywords_export.json
"
```

Output format:
```json
[
  {
    "title": "BERT: Pre-training of Deep Bidirectional Transformers",
    "keywords": ["BERT", "NLP"],
    "source": "regex|gemini|judge",
    "venue": "NAACL",
    "year": 2019
  }
]
```

---

## 7. Expected Output Examples

| Title | Abstract (snippet) | Extracted Keywords |
|-------|-------------------|-------------------|
| "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding" | "We introduce BERT, a new language representation model..." | `["BERT", "language representation", "pre-training"]` |
| "HyDE: Hypothetical Document Embeddings for Zero-shot Dense Retrieval" | "We propose HyDE, a method that uses LLM to generate hypothetical documents..." | `["HyDE", "dense retrieval", "zero-shot", "LLM"]` |
| "ColBERT: Efficient and Effective Passage Search" | "We introduce ColBERT, a ranking model..." | `["ColBERT", "BERT", "passage search"]` |

---

## 8. CLI Options Reference

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | off | Preview without saving |
| `--limit N` | all | Process max N papers |
| `--batch-size N` | 100 | Papers per batch |
| `--no-keybert` | off | Skip KeyBERT, use regex only |
| `--force` | off | Re-extract for papers with existing keywords |
| `--embedding-model` | `all-MiniLM-L6-v2` | Sentence-transformers model for KeyBERT |
| `--llm` | off | Enable LLM keyword extraction |
| `--llm-backend` | `gemini` | LLM backend: `gemini` or `ollama` |
| `--judge` | off | Enable LLM judge validation |
| `--judge-backend` | same as `--llm-backend` | Judge backend: `gemini` or `ollama` |
| `--ollama-model` | `llama3.1:8b` | Ollama model name |
| `--gemini-model` | `gemini-2.0-flash` | Gemini model name |
| `--ollama-timeout` | `180` | Ollama request timeout in seconds |

---

## 9. Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEYS` | Gemini API key(s), comma-separated for round-robin rotation (required for `--llm-backend gemini`) |
| `GEMINI_API_KEY` | Fallback for `GEMINI_API_KEYS` (singular) |
| `GOOGLE_API_KEY` | Fallback (legacy) |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |

### 9.1 Multi-Key Gemini Round-Robin

To distribute rate limits across multiple API keys, set comma-separated keys:

```env
GEMINI_API_KEYS=key1,key2,key3,key4,key5
```

Each API call rotates to the next key using `itertools.cycle`, distributing the load evenly. This applies to both keyword extraction and abstract labeling pipelines.

---

## 10. Module Structure

```
src/core/keyword/
├── __init__.py          # Module exports (KeywordExtractor, ExtractedKeywords, JudgeResult)
├── extractor.py         # KeywordExtractor class (sync extract + async pipeline)
├── patterns.py          # Regex patterns for acronym extraction
├── stopwords.py         # Stopword list and validation
├── llm_base.py          # Pydantic models, prompt templates, ABC base classes
├── gemini.py            # GeminiKeywordExtractor + GeminiJudge (google-genai SDK)
├── ollama.py            # OllamaKeywordExtractor + OllamaJudge (httpx REST API)
└── judge.py             # KeywordJudge wrapper (delegates to backend)
```

---

## 11. Related Documents

- [CLI Reference](../reference/cli.md) - Full CLI command reference
- [Data Model](../architecture/data_model.md) - Qdrant schema details
- [Search Pipeline](./search.md) - How keywords are used in search
