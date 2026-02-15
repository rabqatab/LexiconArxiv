# Data Model & Schema

## 1. Overview

This document defines the data model and schema for the AI Research Insights Engine.

### 1.1 Core vs On-demand Distinction

| Type | Description | Storage |
|------|-------------|---------|
| **Core** | Tier 0/1/2 venue papers | Permanent storage, includes citation graph |
| **On-demand** | Query-time search results | Cache storage, includes Core connection info |

---

## 2. Core Entities

### 2.1 Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐
│  CanonicalPaper │───────│  SourceRecord   │
│  (Normalized)   │ 1   n │  (Per-source)   │
└────────┬────────┘       └─────────────────┘
         │
         │ n
         │
         │ n
┌────────┴────────┐       ┌─────────────────┐
│ CitationEdge    │       │     Author      │
│ (Citation Graph)│       │    (Author)     │
└─────────────────┘       └─────────────────┘

┌─────────────────┐       ┌─────────────────┐
│     Venue       │       │   CoreConnection│
│ (Conf/Journal)  │       │(Core Connection)│
└─────────────────┘       └─────────────────┘
```

---

## 3. Venue Classification

See [Venue Reference](../reference/venues.md) for complete venue details including:
- Tier 0: 11 core venues (NeurIPS, ICML, ICLR, ACL, EMNLP, etc.)
- Tier 1: 14 extended venues (NAACL, EACL, COLING, WSDM, etc.)
- Tier 2: 3+ specialized venues (Legal AI, workshops)

> **Note**: Alt IDs are year-specific Source IDs in OpenAlex. Use OR condition when collecting.

---

## 4. PostgreSQL Schema

### 4.1 canonical_papers

Normalized paper records (Core + cached On-demand)

```sql
CREATE TABLE canonical_papers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Basic info
    title           TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    abstract        TEXT,
    year            INTEGER,
    month           INTEGER,

    -- Paper classification
    paper_type      VARCHAR(50),     -- method, dataset, survey, benchmark
    venue_id        UUID REFERENCES venues(id),

    -- Core-related fields (NEW)
    tier            SMALLINT,        -- 0 = Tier 0, 1 = Tier 1, NULL = On-demand
    is_core         BOOLEAN DEFAULT FALSE,

    -- Identifiers
    doi             VARCHAR(255) UNIQUE,
    arxiv_id        VARCHAR(50) UNIQUE,
    acl_id          VARCHAR(100) UNIQUE,
    openalex_id     VARCHAR(50) UNIQUE,
    semantic_scholar_id VARCHAR(50),

    -- URL
    pdf_url         TEXT,
    abstract_url    TEXT,
    code_url        TEXT,

    -- Metadata
    citation_count  INTEGER DEFAULT 0,
    is_preprint     BOOLEAN DEFAULT FALSE,
    has_published_version BOOLEAN DEFAULT FALSE,

    -- System fields
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_synced_at  TIMESTAMP WITH TIME ZONE,

    CONSTRAINT check_has_identifier CHECK (
        doi IS NOT NULL OR
        arxiv_id IS NOT NULL OR
        acl_id IS NOT NULL OR
        openalex_id IS NOT NULL
    )
);

-- Indexes
CREATE INDEX idx_papers_year ON canonical_papers(year);
CREATE INDEX idx_papers_venue ON canonical_papers(venue_id);
CREATE INDEX idx_papers_type ON canonical_papers(paper_type);
CREATE INDEX idx_papers_tier ON canonical_papers(tier);
CREATE INDEX idx_papers_is_core ON canonical_papers(is_core);
CREATE INDEX idx_papers_title_normalized ON canonical_papers
    USING gin(to_tsvector('english', title_normalized));
CREATE INDEX idx_papers_updated ON canonical_papers(updated_at);
```

### 4.2 venues (Updated)

```sql
CREATE TABLE venues (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(500) NOT NULL,
    name_short      VARCHAR(100),      -- ACL, EMNLP, etc.
    venue_type      VARCHAR(50),       -- conference, journal, workshop, preprint

    -- Tier classification (NEW)
    tier            SMALLINT,          -- 0 = Tier 0, 1 = Tier 1, NULL = other
    field           VARCHAR(50),       -- NLP, ML, AI, DM, IR, Web

    -- Identifiers
    dblp_id         VARCHAR(100),
    openalex_ids    TEXT[],            -- Multiple source IDs possible (NEW)

    UNIQUE(name)
);

CREATE INDEX idx_venues_tier ON venues(tier);
CREATE INDEX idx_venues_field ON venues(field);

-- Tier 0 Venue initial data
INSERT INTO venues (name_short, name, tier, field, venue_type, openalex_ids) VALUES
    ('NeurIPS', 'Neural Information Processing Systems', 0, 'ML', 'conference', ARRAY['S4306420609']),
    ('ICML', 'International Conference on Machine Learning', 0, 'ML', 'conference', ARRAY['S4306419644']),
    ('ICLR', 'International Conference on Learning Representations', 0, 'ML', 'conference', ARRAY['S4306419637']),
    ('AAAI', 'AAAI Conference on Artificial Intelligence', 0, 'AI', 'conference', ARRAY['S4210191458']),
    ('IJCAI', 'International Joint Conference on AI', 0, 'AI', 'conference', ARRAY['S4306419999', 'S4363608755']),
    ('ACL', 'Annual Meeting of the ACL', 0, 'NLP', 'conference', ARRAY['S4306420508', 'S4363608652']),
    ('EMNLP', 'Empirical Methods in NLP', 0, 'NLP', 'conference', ARRAY['S4306418267', 'S4363608991']),
    ('KDD', 'Knowledge Discovery and Data Mining', 0, 'DM', 'conference', ARRAY['S4306420424', 'S4363608767']),
    ('WWW', 'The Web Conference', 0, 'Web', 'conference', ARRAY['S4363608783', 'S4306421067', 'S4363608846']),
    ('SIGIR', 'ACM SIGIR Conference', 0, 'IR', 'conference', ARRAY['S4306418959', 'S4363608773']),
    ('JMLR', 'Journal of Machine Learning Research', 0, 'ML', 'journal', ARRAY['S118988714']),
    -- Tier 1
    ('NAACL', 'North American Chapter of ACL', 1, 'NLP', 'conference', ARRAY['S4306420633', 'S4363608774']),
    ('EACL', 'European Chapter of ACL', 1, 'NLP', 'conference', ARRAY['S4306418011']),
    ('COLING', 'International Conference on Computational Linguistics', 1, 'NLP', 'conference', ARRAY['S4306419219']),
    ('Findings', 'Findings of the ACL', 1, 'NLP', 'conference', ARRAY['S4363605144', 'S4363605604']),
    ('TACL', 'Transactions of the ACL', 1, 'NLP', 'journal', ARRAY['S2729999759']),
    ('CoNLL', 'Conference on Computational Natural Language Learning', 1, 'NLP', 'conference', ARRAY['S4306418031']),
    ('LREC', 'Language Resources and Evaluation Conference', 1, 'NLP', 'conference', ARRAY['S4306424877']),
    ('WSDM', 'Web Search and Data Mining', 1, 'IR', 'conference', ARRAY['S4363608885']),
    ('CIKM', 'Conference on Information and Knowledge Management', 1, 'IR', 'conference', ARRAY['S4363608762']),
    ('ICDM', 'IEEE International Conference on Data Mining', 1, 'DM', 'conference', ARRAY['S4363608061', 'S4363608104']),
    ('ECIR', 'European Conference on Information Retrieval', 1, 'IR', 'conference', ARRAY['S4306418323']),
    ('RecSys', 'ACM Conference on Recommender Systems', 1, 'IR', 'conference', ARRAY['S4306418092']),
    ('TOIS', 'ACM Transactions on Information Systems', 1, 'IR', 'journal', ARRAY['S4394735545']),
    ('ESWA', 'Expert Systems with Applications', 1, 'AI', 'journal', ARRAY['S13144211']),
    -- Tier 2 (Legal AI)
    ('AILaw', 'Artificial Intelligence and Law', 2, 'Legal', 'journal', ARRAY['S96609033']),
    ('ICAIL', 'International Conference on AI and Law', 2, 'Legal', 'conference', ARRAY['S4306419144']),
    ('JURIX', 'International Conference on Legal Knowledge Systems', 2, 'Legal', 'conference', ARRAY['S4306419638']);
```

### 4.3 citation_edges

Citation graph edge table

```sql
CREATE TABLE citation_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Citation relationship: citing_paper -> cited_paper
    citing_paper_id UUID NOT NULL REFERENCES canonical_papers(id),
    cited_paper_id  UUID NOT NULL REFERENCES canonical_papers(id),

    -- Metadata
    citation_context TEXT,           -- Citation context (if available)
    is_core_to_core BOOLEAN,         -- Whether citation is within Core

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(citing_paper_id, cited_paper_id)
);

CREATE INDEX idx_citation_citing ON citation_edges(citing_paper_id);
CREATE INDEX idx_citation_cited ON citation_edges(cited_paper_id);
CREATE INDEX idx_citation_core ON citation_edges(is_core_to_core);
```

### 4.4 core_connections

Core Corpus connection relationships for on-demand papers

```sql
CREATE TABLE core_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Connection relationship: on-demand paper -> core paper
    ondemand_paper_id   UUID NOT NULL REFERENCES canonical_papers(id),
    core_paper_id       UUID NOT NULL REFERENCES canonical_papers(id),

    -- Connection type
    connection_type     VARCHAR(50) NOT NULL,
    -- 'cites_core': Cites a Core paper
    -- 'cited_by_core': Cited by a Core paper
    -- 'published_as': Preprint to published version relationship
    -- 'similar_to': Based on semantic similarity

    -- Confidence
    confidence          FLOAT,        -- 0-1

    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(ondemand_paper_id, core_paper_id, connection_type)
);

CREATE INDEX idx_core_conn_ondemand ON core_connections(ondemand_paper_id);
CREATE INDEX idx_core_conn_core ON core_connections(core_paper_id);
CREATE INDEX idx_core_conn_type ON core_connections(connection_type);
```

### 4.5 source_records

Original records per source

```sql
CREATE TABLE source_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id    UUID REFERENCES canonical_papers(id),

    -- Source info
    source          VARCHAR(50) NOT NULL,  -- openalex, arxiv, acl
    source_id       VARCHAR(255) NOT NULL,

    -- Raw data
    raw_data        JSONB NOT NULL,

    -- OpenAlex citation info (referenced_works)
    referenced_work_ids TEXT[],       -- OpenAlex work IDs

    -- Metadata
    fetched_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE,

    UNIQUE(source, source_id)
);

CREATE INDEX idx_source_canonical ON source_records(canonical_id);
CREATE INDEX idx_source_source ON source_records(source);
```

### 4.6 authors

```sql
CREATE TABLE authors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(500) NOT NULL,
    name_normalized VARCHAR(500) NOT NULL,
    orcid           VARCHAR(50) UNIQUE,

    openalex_id     VARCHAR(50),
    semantic_scholar_id VARCHAR(50),

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_authors_name ON authors(name_normalized);
CREATE INDEX idx_authors_orcid ON authors(orcid);
```

### 4.7 paper_authors

```sql
CREATE TABLE paper_authors (
    paper_id        UUID REFERENCES canonical_papers(id),
    author_id       UUID REFERENCES authors(id),
    position        INTEGER NOT NULL,
    is_corresponding BOOLEAN DEFAULT FALSE,
    affiliation_raw TEXT,

    PRIMARY KEY (paper_id, author_id)
);

CREATE INDEX idx_paper_authors_author ON paper_authors(author_id);
```

### 4.8 paper_versions

Preprint ↔ Publication connection

```sql
CREATE TABLE paper_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_paper_id UUID REFERENCES canonical_papers(id),
    related_paper_id UUID REFERENCES canonical_papers(id),

    relation_type   VARCHAR(50) NOT NULL,
    confidence      FLOAT,
    matched_by      VARCHAR(50),

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(primary_paper_id, related_paper_id, relation_type)
);
```

---

## 5. Qdrant Collection Schema

### 5.1 Payload-Only Architecture

The collection uses **payload-only storage** to decouple metadata from embeddings:

```json
{
  "collection_name": "lexicon_arxiv",
  "vectors": {},  // Empty - payload-only storage
  ...
}
```

**Benefits**:
- **Decouple enrichment from embeddings**: Run collection + enrichment pipeline without vectors
- **Flexible dimensions**: Add embeddings later with any dimension (384, 768, 1536, etc.)
- **Named vectors**: Support multiple embedding types (title, abstract, full-text)
- **No wasted storage**: No placeholder zero vectors during collection phase

**Implementation Note**: When upserting points, the `qdrant-client` library requires the `vector` field in `PointStruct`. Pass an empty dict `{}` for payload-only storage:

```python
# Upserting without actual vectors (payload-only)
client.upsert(
    collection_name="lexicon_arxiv",
    points=[
        models.PointStruct(
            id="point-uuid",
            vector={},  # Empty dict required by qdrant-client
            payload={"title": "Paper Title", ...},
        )
    ],
)
```

### 5.2 Adding Vectors Later (Named Vectors)

After collection/enrichment, add vectors using Qdrant's named vectors feature:

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models

client = QdrantClient(url="http://localhost:6333")

# Step 1: Add vector configuration to existing collection
client.update_collection(
    collection_name="lexicon_arxiv",
    vectors_config={
        "abstract_embed": models.VectorParams(
            size=1536,  # e.g., OpenAI ada-002
            distance=models.Distance.COSINE,
        ),
    },
)

# Step 2: Update points with vectors
client.update_vectors(
    collection_name="lexicon_arxiv",
    points=[
        models.PointVectors(
            id="point-uuid-here",
            vector={"abstract_embed": [0.1, 0.2, ...]}  # 1536-dim vector
        )
    ]
)

# Step 3: Search using named vector
results = client.search(
    collection_name="lexicon_arxiv",
    query_vector=("abstract_embed", query_embedding),
    limit=10,
)
```

### 5.3 Multiple Embedding Types (Future)

Support for multiple embedding models:

```python
# Add multiple named vectors
client.update_collection(
    collection_name="lexicon_arxiv",
    vectors_config={
        "title_embed": models.VectorParams(size=384, distance=models.Distance.COSINE),
        "abstract_embed": models.VectorParams(size=1536, distance=models.Distance.COSINE),
        "full_embed": models.VectorParams(size=768, distance=models.Distance.COSINE),
    },
)
```

| Vector Name | Model | Dimension | Use Case |
|-------------|-------|-----------|----------|
| `title_embed` | all-MiniLM-L6-v2 | 384 | Fast title search |
| `abstract_embed` | text-embedding-ada-002 | 1536 | High-quality semantic |
| `full_embed` | SPECTER2 | 768 | Scientific papers |

### 5.4 paper_embeddings collection (Payload Schema)

```json
{
  "collection_name": "lexicon_arxiv",
  "vectors": {},  // Payload-only, vectors added via update_collection
  "payload_schema": {
    "paper_id": "keyword",
    "source": "keyword",        // openalex, acl_anthology, dblp
    "source_id": "keyword",
    "title": "text",
    "abstract": "text",
    "year": "integer",
    "venue": "keyword",
    "tier": "integer",         // 0, 1, 2, or null
    "is_core": "bool",
    "is_stub": "bool",         // true for external reference papers
    "paper_type": "keyword",
    "venue_type": "keyword",   // conference, journal, workshop
    "is_preprint": "bool",
    "citation_count": "integer",
    "field": "keyword",
    "doi": "keyword",
    "referenced_works": "keyword[]",
    "cited_by": "keyword[]",   // Internal paper IDs that cite this paper
    "cited_by_count_internal": "integer",
    "keywords": "keyword[]",   // Extracted keywords (LLM-first, regex + KeyBERT fallback)
    "keywords_source": "keyword",  // pipe-delimited: "gemini|judge", "ollama", "regex|keybert", etc.
    "keywords_structured": "object",  // Categorized: {task, method, model, domain, dataset, contribution_type, modality}
    "abstract_structure": "object",   // Sentence-level: {task, domain, background, approach, method, result, contribution}
    "abstract_structure_source": "keyword"  // "gemini", "ollama", or "none"
  }
}
```

> **Note**: HNSW config is only applied when vectors are added via `update_collection()`.
```

### 5.2 Qdrant Filters for Core-first Search

```python
# Core papers priority search
core_filter = Filter(
    should=[
        FieldCondition(key="is_core", match=MatchValue(value=True)),
    ]
)

# Tier 0 only
tier0_filter = Filter(
    must=[
        FieldCondition(key="tier", match=MatchValue(value=0)),
    ]
)

# Search within specific field
nlp_filter = Filter(
    must=[
        FieldCondition(key="field", match=MatchValue(value="NLP")),
        FieldCondition(key="is_core", match=MatchValue(value=True)),
    ]
)
```

---

## 6. Data Types Reference

### 6.1 Tier Values

| Value | Description | Venues |
|-------|-------------|--------|
| `0` | Tier 0 — Core Corpus (required collection) | 11 venues (NeurIPS, ICML, ACL, etc.) |
| `1` | Tier 1 — Extended Corpus (optional collection) | 13 venues (NAACL, EACL, RecSys, etc.) |
| `2` | Tier 2 — Specialized Corpus (Legal AI) | 3 venues (AILaw, ICAIL, JURIX) |
| `NULL` | On-demand — collected at query time | - |

### 6.2 Core Connection Types

| Value | Description |
|-------|-------------|
| `cites_core` | On-demand paper cites a Core paper |
| `cited_by_core` | On-demand paper is cited by a Core paper |
| `published_as` | Preprint to Core published version relationship |
| `similar_to` | Connection based on semantic similarity |

### 6.3 Paper Types

| Value | Description |
|-------|-------------|
| `method` | New method/model proposal |
| `dataset` | Dataset release |
| `benchmark` | Benchmark/evaluation |
| `survey` | Survey/review paper |
| `analysis` | Analysis/experimental study |
| `application` | Application/case study |
| `position` | Position paper |
| `demo` | System demo |

### 6.4 Venue Types

| Value | Description |
|-------|-------------|
| `conference` | Main conference |
| `workshop` | Workshop |
| `journal` | Journal |
| `preprint` | Preprint (arXiv, etc.) |

### 6.5 Field Categories

| Value | Description | Example Venues |
|-------|-------------|----------------|
| `NLP` | Natural Language Processing | ACL, EMNLP, NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC |
| `ML` | Machine Learning | NeurIPS, ICML, ICLR, JMLR |
| `AI` | Artificial Intelligence (General) | AAAI, IJCAI, ESWA |
| `DM` | Data Mining | KDD, ICDM |
| `IR` | Information Retrieval | SIGIR, WSDM, CIKM, ECIR, RecSys, TOIS |
| `Web` | Web | WWW |
| `Legal` | Legal AI / Computational Law | AILaw, ICAIL, JURIX |

---

## 7. Data Integrity Rules

### 7.1 Core Corpus Rules

1. **Tier 0/1/2 papers have is_core = TRUE**
2. **Tier 0/1/2 papers require citation_edges construction**
3. **On-demand papers with core_connections are cached**

### 7.2 Deduplication Rules

1. **DOI Match**: Same DOI = same paper
2. **arXiv ID Match**: Same arXiv ID = same paper
3. **Title+Year Match**: Normalized title + year + first author match = same paper

### 7.3 Citation Graph Rules

1. **Core internal citations**: `is_core_to_core = TRUE`
2. **Citation direction**: `citing_paper_id` → `cited_paper_id`
3. **Built from OpenAlex referenced_works**

### 7.4 Normalization Rules

**Title normalization**:
```python
def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r'[^\w\s]', '', title)
    title = ' '.join(title.split())
    return title
```

**Author name normalization**:
```python
def normalize_author(name: str) -> str:
    parts = name.replace(',', ' ').split()
    return ' '.join(sorted([p.lower() for p in parts]))
```

---

## 8. Migration Notes

### 8.1 From v1 to v2

Existing data migration:

```sql
-- Assign tier to existing papers
UPDATE canonical_papers p
SET tier = v.tier, is_core = (v.tier IS NOT NULL)
FROM venues v
WHERE p.venue_id = v.id AND v.tier IN (0, 1);

-- Create citation edges (based on referenced_work_ids from source_records)
INSERT INTO citation_edges (citing_paper_id, cited_paper_id, is_core_to_core)
SELECT
    sr.canonical_id,
    ref_paper.id,
    (p1.is_core AND ref_paper.is_core)
FROM source_records sr
CROSS JOIN LATERAL unnest(sr.referenced_work_ids) AS ref_id
JOIN canonical_papers ref_paper ON ref_paper.openalex_id = ref_id
JOIN canonical_papers p1 ON p1.id = sr.canonical_id
WHERE sr.source = 'openalex';
```
