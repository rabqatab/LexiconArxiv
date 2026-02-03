# Data Model & Schema

## 1. Overview

본 문서는 AI 연구 인사이트 엔진의 데이터 모델과 스키마를 정의합니다.

### 1.1 Core vs On-demand 구분

| 구분 | 설명 | 저장 |
|------|------|------|
| **Core** | Tier 0/1 venue 논문 | 영구 저장, 인용 그래프 포함 |
| **On-demand** | 질의 시점 검색 결과 | 캐시 저장, Core 연결 정보 포함 |

---

## 2. Core Entities

### 2.1 Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐
│  CanonicalPaper │───────│  SourceRecord   │
│  (논문 정규화)   │ 1   n │  (소스별 원본)   │
└────────┬────────┘       └─────────────────┘
         │
         │ n
         │
         │ n
┌────────┴────────┐       ┌─────────────────┐
│ CitationEdge    │       │     Author      │
│ (인용 그래프)    │       │    (저자)       │
└─────────────────┘       └─────────────────┘

┌─────────────────┐       ┌─────────────────┐
│     Venue       │       │   CoreConnection│
│   (학회/저널)   │       │  (Core 연결)    │
└─────────────────┘       └─────────────────┘
```

---

## 3. Venue Classification

### 3.1 Tier 0 — Core Corpus (11 venues)

| Venue | Full Name | Field | Type | OpenAlex Source IDs | Alt IDs |
|-------|-----------|-------|------|---------------------|---------|
| NeurIPS | Neural Information Processing Systems | ML | conference | S4306420609 | - |
| ICML | International Conference on Machine Learning | ML | conference | S4306419644 | - |
| ICLR | International Conference on Learning Representations | ML | conference | S4306419637 | - |
| AAAI | AAAI Conference on Artificial Intelligence | AI | conference | S4210191458 | - |
| IJCAI | International Joint Conference on AI | AI | conference | S4306419999 | S4363608755 |
| ACL | Annual Meeting of the ACL | NLP | conference | S4306420508 | S4363608652 |
| EMNLP | Empirical Methods in NLP | NLP | conference | S4306418267 | S4363608991 |
| KDD | Knowledge Discovery and Data Mining | DM | conference | S4306420424 | S4363608767 |
| WWW | The Web Conference | Web | conference | S4363608783 | S4306421067, S4363608846 |
| SIGIR | ACM SIGIR Conference | IR | conference | S4306418959 | S4363608773 |
| JMLR | Journal of Machine Learning Research | ML | journal | S118988714 | - |

### 3.2 Tier 1 — Extended Corpus (13 venues)

| Venue | Full Name | Field | Type | OpenAlex Source IDs | Alt IDs |
|-------|-----------|-------|------|---------------------|---------|
| NAACL | North American Chapter of ACL | NLP | conference | S4306420633 | S4363608774 |
| EACL | European Chapter of ACL | NLP | conference | S4306418011 | - |
| COLING | International Conference on Computational Linguistics | NLP | conference | S4306419219 | - |
| Findings | Findings of the ACL | NLP | conference | S4363605144 | S4363605604 |
| TACL | Transactions of the ACL | NLP | journal | S2729999759 | - |
| CoNLL | Conference on Computational Natural Language Learning | NLP | conference | S4306418031 | - |
| LREC | Language Resources and Evaluation Conference | NLP | conference | S4306424877 | - |
| WSDM | Web Search and Data Mining | IR | conference | S4363608885 | - |
| CIKM | Conference on Information and Knowledge Management | IR | conference | S4363608762 | - |
| ICDM | IEEE International Conference on Data Mining | DM | conference | S4363608061 | S4363608104 |
| ECIR | European Conference on Information Retrieval | IR | conference | S4306418323 | - |
| RecSys | ACM Conference on Recommender Systems | IR | conference | S4306418092 | - |
| TOIS | ACM Transactions on Information Systems | IR | journal | S4394735545 | - |
| ESWA | Expert Systems with Applications | AI | journal | S13144211 | - |

### 3.3 Tier 2 — Specialized Corpus (Legal AI, 3 venues)

| Venue | Full Name | Field | Type | OpenAlex Source IDs | Notes |
|-------|-----------|-------|------|---------------------|-------|
| AILaw | Artificial Intelligence and Law | Legal | journal | S96609033 | Primary Legal AI journal |
| ICAIL | International Conference on AI and Law | Legal | conference | S4306419144 | Limited OpenAlex coverage |
| JURIX | International Conference on Legal Knowledge Systems | Legal | conference | S4306419638 | Limited OpenAlex coverage |

> **Note**: Alt IDs는 OpenAlex에서 연도별로 분리된 Source ID. 수집 시 OR 조건으로 결합 필요.

---

## 4. PostgreSQL Schema

### 4.1 canonical_papers

정규화된 논문 레코드 (Core + 캐시된 On-demand)

```sql
CREATE TABLE canonical_papers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 기본 정보
    title           TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    abstract        TEXT,
    year            INTEGER,
    month           INTEGER,

    -- 논문 분류
    paper_type      VARCHAR(50),     -- method, dataset, survey, benchmark
    venue_id        UUID REFERENCES venues(id),

    -- Core 관련 필드 (NEW)
    tier            SMALLINT,        -- 0 = Tier 0, 1 = Tier 1, NULL = On-demand
    is_core         BOOLEAN DEFAULT FALSE,

    -- 식별자
    doi             VARCHAR(255) UNIQUE,
    arxiv_id        VARCHAR(50) UNIQUE,
    acl_id          VARCHAR(100) UNIQUE,
    openalex_id     VARCHAR(50) UNIQUE,
    semantic_scholar_id VARCHAR(50),

    -- URL
    pdf_url         TEXT,
    abstract_url    TEXT,
    code_url        TEXT,

    -- 메타데이터
    citation_count  INTEGER DEFAULT 0,
    is_preprint     BOOLEAN DEFAULT FALSE,
    has_published_version BOOLEAN DEFAULT FALSE,

    -- 시스템 필드
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

-- 인덱스
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

    -- Tier 분류 (NEW)
    tier            SMALLINT,          -- 0 = Tier 0, 1 = Tier 1, NULL = other
    field           VARCHAR(50),       -- NLP, ML, AI, DM, IR, Web

    -- 식별자
    dblp_id         VARCHAR(100),
    openalex_ids    TEXT[],            -- 여러 source ID 가능 (NEW)

    UNIQUE(name)
);

CREATE INDEX idx_venues_tier ON venues(tier);
CREATE INDEX idx_venues_field ON venues(field);

-- Tier 0 Venue 초기 데이터
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

### 4.3 citation_edges (NEW)

인용 그래프 엣지 테이블

```sql
CREATE TABLE citation_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 인용 관계: citing_paper -> cited_paper
    citing_paper_id UUID NOT NULL REFERENCES canonical_papers(id),
    cited_paper_id  UUID NOT NULL REFERENCES canonical_papers(id),

    -- 메타데이터
    citation_context TEXT,           -- 인용 맥락 (있는 경우)
    is_core_to_core BOOLEAN,         -- Core 내부 인용 여부

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(citing_paper_id, cited_paper_id)
);

CREATE INDEX idx_citation_citing ON citation_edges(citing_paper_id);
CREATE INDEX idx_citation_cited ON citation_edges(cited_paper_id);
CREATE INDEX idx_citation_core ON citation_edges(is_core_to_core);
```

### 4.4 core_connections (NEW)

On-demand 논문의 Core Corpus 연결 관계

```sql
CREATE TABLE core_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 연결 관계: on-demand paper -> core paper
    ondemand_paper_id   UUID NOT NULL REFERENCES canonical_papers(id),
    core_paper_id       UUID NOT NULL REFERENCES canonical_papers(id),

    -- 연결 유형
    connection_type     VARCHAR(50) NOT NULL,
    -- 'cites_core': Core 논문을 인용
    -- 'cited_by_core': Core 논문에 인용됨
    -- 'published_as': 프리프린트 → 출판본 관계
    -- 'similar_to': Semantic 유사도 기반

    -- 신뢰도
    confidence          FLOAT,        -- 0-1

    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(ondemand_paper_id, core_paper_id, connection_type)
);

CREATE INDEX idx_core_conn_ondemand ON core_connections(ondemand_paper_id);
CREATE INDEX idx_core_conn_core ON core_connections(core_paper_id);
CREATE INDEX idx_core_conn_type ON core_connections(connection_type);
```

### 4.5 source_records

각 소스별 원본 레코드

```sql
CREATE TABLE source_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id    UUID REFERENCES canonical_papers(id),

    -- 소스 정보
    source          VARCHAR(50) NOT NULL,  -- openalex, arxiv, acl
    source_id       VARCHAR(255) NOT NULL,

    -- 원본 데이터
    raw_data        JSONB NOT NULL,

    -- OpenAlex 인용 정보 (referenced_works)
    referenced_work_ids TEXT[],       -- OpenAlex work IDs

    -- 메타데이터
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

프리프린트 ↔ 출판본 연결

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

### 5.1 paper_embeddings collection

```json
{
  "collection_name": "paper_embeddings",
  "vectors": {
    "size": 768,
    "distance": "Cosine"
  },
  "payload_schema": {
    "paper_id": "keyword",
    "source": "keyword",        // openalex, acl_anthology, dblp
    "source_id": "keyword",
    "title": "text",
    "year": "integer",
    "venue": "keyword",
    "tier": "integer",         // 0, 1, 2, or null
    "is_core": "bool",
    "paper_type": "keyword",
    "venue_type": "keyword",   // conference, journal, workshop
    "is_preprint": "bool",
    "citation_count": "integer",
    "field": "keyword",
    "doi": "keyword",
    "referenced_works": "keyword[]"
  },
  "optimizers_config": {
    "indexing_threshold": 20000
  },
  "hnsw_config": {
    "m": 16,
    "ef_construct": 100
  }
}
```

### 5.2 Qdrant Filters for Core-first Search

```python
# Core 논문 우선 검색
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

# 특정 field 내 검색
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
| `0` | Tier 0 — Core Corpus (필수 수집) | 11 venues (NeurIPS, ICML, ACL, etc.) |
| `1` | Tier 1 — Extended Corpus (선택 수집) | 13 venues (NAACL, EACL, RecSys, etc.) |
| `2` | Tier 2 — Specialized Corpus (Legal AI) | 3 venues (AILaw, ICAIL, JURIX) |
| `NULL` | On-demand — 질의 시점 수집 | - |

### 6.2 Core Connection Types

| Value | Description |
|-------|-------------|
| `cites_core` | On-demand 논문이 Core 논문을 인용 |
| `cited_by_core` | On-demand 논문이 Core 논문에 인용됨 |
| `published_as` | 프리프린트 → Core 출판본 관계 |
| `similar_to` | Semantic 유사도 기반 연결 |

### 6.3 Paper Types

| Value | Description |
|-------|-------------|
| `method` | 새로운 방법론/모델 제안 |
| `dataset` | 데이터셋 공개 |
| `benchmark` | 벤치마크/평가 |
| `survey` | 서베이/리뷰 논문 |
| `analysis` | 분석/실험 연구 |
| `application` | 응용/사례 연구 |
| `position` | 포지션 페이퍼 |
| `demo` | 시스템 데모 |

### 6.4 Venue Types

| Value | Description |
|-------|-------------|
| `conference` | 학회 본회의 |
| `workshop` | 워크숍 |
| `journal` | 저널 |
| `preprint` | 프리프린트 (arXiv 등) |

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

1. **Tier 0/1 논문은 is_core = TRUE**
2. **Tier 0/1 논문은 citation_edges 구축 필수**
3. **On-demand 논문은 core_connections 있으면 캐시 저장**

### 7.2 Deduplication Rules

1. **DOI Match**: DOI가 동일하면 같은 논문
2. **arXiv ID Match**: arXiv ID가 동일하면 같은 논문
3. **Title+Year Match**: 정규화된 제목 + 연도 + 첫 저자가 동일하면 같은 논문

### 7.3 Citation Graph Rules

1. **Core 내부 인용**: `is_core_to_core = TRUE`
2. **인용 방향**: `citing_paper_id` → `cited_paper_id`
3. **OpenAlex referenced_works 기반 구축**

### 7.4 Normalization Rules

**제목 정규화**:
```python
def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r'[^\w\s]', '', title)
    title = ' '.join(title.split())
    return title
```

**저자 이름 정규화**:
```python
def normalize_author(name: str) -> str:
    parts = name.replace(',', ' ').split()
    return ' '.join(sorted([p.lower() for p in parts]))
```

---

## 8. Migration Notes

### 8.1 From v1 to v2

기존 데이터 마이그레이션:

```sql
-- 기존 논문에 tier 할당
UPDATE canonical_papers p
SET tier = v.tier, is_core = (v.tier IS NOT NULL)
FROM venues v
WHERE p.venue_id = v.id AND v.tier IN (0, 1);

-- Citation edges 생성 (source_records의 referenced_work_ids 기반)
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
