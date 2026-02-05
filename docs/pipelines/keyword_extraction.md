# Keyword Extraction Pipeline

## 1. Overview

This document describes the keyword/acronym extraction pipeline for papers in the Core Corpus.

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
# Extract keywords for all papers (regex + KeyBERT)
python -m src.cli.core_collect extract-keywords

# Use only regex patterns (faster, no model loading)
python -m src.cli.core_collect extract-keywords --no-keybert

# Preview without saving
python -m src.cli.core_collect extract-keywords --dry-run --limit 10

# Re-extract for ALL papers (including those with existing keywords)
python -m src.cli.core_collect extract-keywords --force

# Limit number of papers to process
python -m src.cli.core_collect extract-keywords --limit 1000

# Adjust batch size
python -m src.cli.core_collect extract-keywords --batch-size 200
```

### 2.2 View Statistics

```bash
# Show keyword extraction statistics
python -m src.cli.core_collect keyword-stats

# Output as JSON
python -m src.cli.core_collect keyword-stats --json
```

### 2.3 Clear Keywords

```bash
# Clear checkpoint (restart from beginning)
python -m src.cli.core_collect clear-keyword-checkpoint

# Clear all keywords from corpus
python -m src.cli.core_collect clear-keywords --confirm
```

---

## 3. Extraction Behavior

### 3.1 Default Mode (skip existing)

By default, papers that already have keywords are **skipped**:

```bash
python -m src.cli.core_collect extract-keywords
# Only processes papers where keywords = []
```

### 3.2 Force Mode (re-extract all)

With `--force`, all papers are re-processed and keywords are **replaced**:

```bash
python -m src.cli.core_collect extract-keywords --force
# Re-extracts for ALL papers, replacing existing keywords
```

### 3.3 Extraction Modes

| Mode | Command | Description |
|------|---------|-------------|
| **Full** | `extract-keywords` | Regex + KeyBERT (default) |
| **Regex Only** | `extract-keywords --no-keybert` | Fast, acronyms only |
| **Re-extract** | `extract-keywords --force` | Replace existing keywords |

---

## 4. Two-Phase Extraction Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                 Keyword Extraction Pipeline                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │   Qdrant    │───▶│  Phase 1    │───▶│     Phase 2         │  │
│  │  (papers)   │    │  Regex      │    │     KeyBERT         │  │
│  └─────────────┘    │  Extraction │    │     Extraction      │  │
│                     └──────┬──────┘    └──────────┬──────────┘  │
│                            │                      │              │
│                            ▼                      ▼              │
│                     ┌─────────────┐    ┌─────────────────────┐  │
│                     │  Acronyms   │    │  Semantic Keywords  │  │
│                     │  from Title │    │  from Abstract      │  │
│                     │  & Abstract │    │  (KeyBERT)          │  │
│                     └──────┬──────┘    └──────────┬──────────┘  │
│                            │                      │              │
│                            └──────────┬───────────┘              │
│                                       ▼                          │
│                              ┌─────────────┐                     │
│                              │   Filter    │                     │
│                              │   & Merge   │                     │
│                              └──────┬──────┘                     │
│                                     │                            │
│                                     ▼                            │
│                              ┌─────────────┐                     │
│                              │   Qdrant    │                     │
│                              │  (keywords) │                     │
│                              └─────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 Phase 1: Regex-based Acronym Extraction

Extracts explicit acronyms and model names from title and abstract.

#### Title Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| `ACRONYM: Description` | "BERT: Pre-training of..." | `^([A-Z][A-Za-z0-9\-]{1,10}):\s` |
| `ACRONYM - Description` | "ColBERT - Efficient..." | `^([A-Z][A-Za-z0-9]{1,10})\s*[-–—]\s` |
| `Description (ACRONYM)` | "...Understanding (BERT)" | `\(([A-Z][A-Za-z0-9\-]{1,10})\)\s*$` |
| Inline ACRONYM | "BERT-based Models..." | `\b([A-Z]{2,10})\b` (with validation) |

#### Abstract Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| "We propose X" | "We introduce HyDE, a method..." | `(?:introduce\|propose\|present)\s+([A-Z][A-Za-z0-9\-]+)` |
| "called X" | "...called BERT..." | `called\s+([A-Z][A-Za-z0-9]+)` |
| Defined acronym | "...Retrieval-Augmented Generation (RAG)..." | `\(([A-Z]{2,8})\)` |
| Inline acronym | "...using LLMs for..." | `\b([A-Z]{2,10}s?)\b` |

### 4.2 Phase 2: KeyBERT Semantic Extraction

Extracts semantically important keywords from abstract using transformer embeddings.

```python
from keybert import KeyBERT

kw_model = KeyBERT()

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

---

## 5. Filtering & Validation

### 5.1 Stopword List

Common words and meaningless acronyms are filtered:

```python
STOPWORDS = {
    # Common words
    "IT", "IS", "OR", "AN", "AS", "AT", "BE", "BY", "THE", "FOR", "AND",

    # Section headers
    "INTRODUCTION", "CONCLUSION", "ABSTRACT", "METHODS",

    # Generic terms
    "PAPER", "STUDY", "MODEL", "SYSTEM", "APPROACH",

    # Common title words
    "LEARNING", "NEURAL", "NETWORK", "DEEP", "DATA",
}
```

### 5.2 Validation Rules

| Rule | Description |
|------|-------------|
| Min length | 2+ characters |
| Max length | 15 characters or less |
| Characters | Letters, numbers, hyphens only |
| Stopwords | Filtered out |

---

## 6. Data Model

### 6.1 Qdrant Payload Fields

```json
{
  "keywords": ["BERT", "NLP", "language model"],
  "keywords_source": "regex"  // or "keybert", "both", "none"
}
```

### 6.2 Export Format

Keywords can be exported to JSON:

```bash
# Export is done via Python script
python -c "
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
    "source": "regex",
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

## 8. Module Structure

```
src/core/keyword/
├── __init__.py          # Module exports
├── extractor.py         # KeywordExtractor class
├── patterns.py          # Regex patterns for acronym extraction
└── stopwords.py         # Stopword list and validation
```

---

## 9. Related Documents

- [CLI Reference](../reference/cli.md) - Full CLI command reference
- [Data Model](../architecture/data_model.md) - Qdrant schema details
- [Search Pipeline](./search.md) - How keywords are used in search
