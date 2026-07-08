# Keyword Extraction Pipeline

## 1. Overview

This document describes the keyword/acronym extraction pipeline for papers in the Core Corpus.

> **History:** an optional LLM extraction/judge path (Gemini, later Ollama) existed through v0.13.4 but was never enabled in production. Gemini was removed in v0.12; the remaining Ollama keyword path was deleted in v0.13.5 (ponytail wave, 2026-07-08). Extraction is now regex + KeyBERT only. Historical `keywords_source` values from the LLM era remain on old points — see §6.

### 1.1 Purpose

| Purpose | Description | Example |
|---------|-------------|---------|
| **Acronym Extraction** | Extract model/method names from title/abstract | "HyDE: Hypothetical..." → `["HyDE"]` |
| **Semantic Keywords** | Extract key concepts from abstract | "...retrieval augmented generation..." → `["retrieval", "generation"]` |
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
# Production (default): regex + KeyBERT
uv run python -m src.cli.core_collect extract-keywords

# Fastest: regex only (no model loading)
uv run python -m src.cli.core_collect extract-keywords --no-keybert

# Better embedding model for KeyBERT
uv run python -m src.cli.core_collect extract-keywords --embedding-model all-mpnet-base-v2

# Preview without saving
uv run python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Re-extract for ALL papers (including those with existing keywords)
uv run python -m src.cli.core_collect extract-keywords --force

# Limit number of papers to process
uv run python -m src.cli.core_collect extract-keywords --limit 1000

# True-incremental scope (Step 5 of the incremental pipeline)
uv run python -m src.cli.core_collect extract-keywords --recent-days 9
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
| **Default** | `extract-keywords` | Regex + KeyBERT |
| **Regex Only** | `extract-keywords --no-keybert` | Fast, acronyms only |
| **Re-extract** | `extract-keywords --force` | Replace existing keywords |

---

## 4. Extraction Phases

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

If KeyBERT is not installed, the extractor logs a warning and continues regex-only.

#### KeyBERT Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| `keyphrase_ngram_range` | (1, 2) | 1-2 word keyphrases |
| `top_n` | 5 | Max 5 keywords per paper |
| `use_mmr` | True | Enable diversity |
| `diversity` | 0.7 | Diversity level |
| `min_score` | 0.3 | Minimum confidence threshold |
| `embedding_model` | `all-MiniLM-L6-v2` | Default sentence-transformers model (configurable) |

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
| `"regex"` | Regex only |
| `"keybert"` | KeyBERT only |
| `"both"` | Regex + KeyBERT |
| `"none"` | No keywords extracted |
| `"gemini"`, `"ollama"`, `"...\|judge"` | **Historical** — written by the removed LLM path (pre-v0.13.5); still present on old points |

### 6.2 Qdrant Payload Fields

```json
{
  "keywords": ["BERT", "NLP", "language model"],
  "keywords_source": "both"
}
```

See [`docs/reference/qdrant-payload-catalog.md`](../reference/qdrant-payload-catalog.md) for the full field catalog.

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
| `--recent-days N` | off | Only papers fetched in the last N days (true-incremental) |

---

## 9. Module Structure

```
src/core/keyword/
├── __init__.py          # Module exports (KeywordExtractor, patterns, stopwords)
├── extractor.py         # KeywordExtractor class (regex + KeyBERT)
├── patterns.py          # Regex patterns for acronym extraction
└── stopwords.py         # Stopword list and validation
```

---

## 10. Related Documents

- [CLI Reference](../reference/cli.md) - Full CLI command reference
- [Data Model](../architecture/data_model.md) - Qdrant schema details
- [Search Pipeline](./search.md) - How keywords are used in search
