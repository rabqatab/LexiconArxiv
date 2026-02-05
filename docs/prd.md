# Product Requirements Document

## AI Research Insights Engine — Core + On-demand

> **An AI research insights engine that uses top-tier research as anchors to reveal research trends, citation graphs, and notable papers.**

---

## 1. Problem Definition

AI/NLP researchers continuously face the following challenges:

| Problem | Impact |
|---------|--------|
| Too many papers | Difficult to identify **current important research trends** |
| Opaque Google Scholar ranking | High recall but **search logic is not trustworthy** |
| Limitations of recommendation systems (Elicit, etc.) | Individual recommendations without overall context |
| Disconnect between arXiv and top-tier | **Connection between latest preprints and verified research is not visible** |

---

## 2. Product Vision

**Not "an AI that answers questions"**
**but "an engine that shows where AI research is heading, anchored on top-tier research"**

### Core Values
- **Core Corpus**: Use top-tier venue papers as anchors
- **Research Graph**: Visualize citation/reference relationships between papers
- **Trend Analysis**: Automatic selection of research trends and notable papers
- **On-demand Extension**: Show connection between latest arXiv and Core

---

## 3. Domain Scope

### Included (In-scope)
- **NLP / Language**: ACL, EMNLP, NAACL, COLING, EACL
- **ML General**: NeurIPS, ICML, ICLR
- **AI General**: AAAI, IJCAI
- **Data Mining / Web / IR**: KDD, WWW, SIGIR, WSDM, CIKM, ICDM

### Excluded (Out-of-scope)
- Computer Vision (CVPR, ICCV, ECCV)
- Robotics (ICRA, IROS)
- Speech/Audio (ICASSP, Interspeech)

---

## 4. Core Strategy: Core + On-demand

### 4.1 Core Corpus (Pre-collected)

| Tier | Venues | Description |
|------|--------|-------------|
| **Tier 0** | NeurIPS, ICML, ICLR, AAAI, IJCAI, ACL, EMNLP, KDD, WWW, SIGIR | Complete collection mandatory |
| **Tier 1** | NAACL, COLING, EACL, WSDM, CIKM, ICDM | Pre-collected, lower priority |

- **Complete collection**: All papers from these venues
- **Citation graph**: Paper connections based on `referenced_works`
- **Embeddings**: Abstract-based semantic search support

### 4.2 On-demand Retrieval (Query-time)

- Search arXiv / OpenAlex with **narrow query** at user query time
- Highlight papers connected to Core Corpus
- Label papers without connection as "Unverified"

---

## 5. Core Features

### 5.1 Search & Discovery
- Natural language query → research intent interpretation
- Core-based hybrid search (BM25 + Semantic)
- Keyword/acronym extraction (Regex + KeyBERT) - supports exact paper retrieval (e.g., "HyDE paper")
- On-demand latest paper extension

### 5.2 Research Graph
- Citation network between Core papers
- Visualize specific paper's influence
- Show arXiv → Core connections

### 5.3 Trends & Notable
- Year/topic research trends
- Automatic notable research selection (based on citations, venue, recency)
- Clustering-based topic classification

### 5.4 Export & Integration
- BibTeX / CSV / JSON export
- REST API
- Saved queries & alerts

---

## 6. MVP Roadmap

### MVP-1: Tier 0 Core + Basic Graph
- Complete Tier 0 venue collection
- Basic search (BM25 + semantic)
- Citation graph visualization

### MVP-2: Tier 1 + On-demand Extension
- Add Tier 1 venues
- arXiv on-demand search
- Core connection display

### MVP-3: Trends + API/Agent Integration
- Trend analysis dashboard
- Automatic notable paper selection
- Public REST API
- Saved queries & alerts

---

## 7. Target Users

### Primary
- AI/NLP PhD students and Postdocs
- Industry research lab researchers
- Review/survey paper authors

### Secondary
- New graduate students (literature exploration phase)
- Technical strategy / research engineers

---

## 8. Competitive Differentiation

| Feature | Google Scholar | Semantic Scholar | Elicit | **This Product** |
|---------|---------------|-----------------|--------|------------------|
| Top-tier anchor | No | Partial | No | **Yes** |
| Research graph | No | Partial | No | **Yes** |
| Core-arXiv connection | No | No | No | **Yes** |
| Trend visualization | No | Partial | No | **Yes** |
| Search transparency | No | No | No | **Yes** |

---

## 9. Success Metrics

### Quantitative
| Metric | Target |
|--------|--------|
| Core Corpus coverage | Tier 0 venue 95%+ |
| Search latency P95 | < 2 seconds |
| Graph loading P95 | < 3 seconds |
| Core-arXiv connection rate | > 30% |

### Qualitative
- "I can see the research flow" feedback
- Usage in review/survey writing
- Usefulness of notable selection

---

## 10. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Venue paper collection gaps | Incomplete Core | Use multiple sources (OpenAlex + ACL Anthology + DBLP) |
| Incomplete citation graph | Missing connections | OpenAlex `referenced_works` + Crossref supplementation |
| "How is this different from Scholar?" | User churn | Emphasize graph/trend UI |
| Embedding costs | Increased operating costs | Abstract priority, batch processing |

---

## 11. Related Documents

| Document | Description |
|----------|-------------|
| [Architecture](./architecture/overview.md) | System architecture |
| [API Specification](./architecture/api.md) | API specification |
| [Data Model](./architecture/data_model.md) | Data schema |
| [Search Pipeline](./pipelines/search.md) | Search pipeline |
| [Data Collection](./pipelines/data_collection.md) | Data collection strategy |
| [Keyword Extraction](./pipelines/keyword_extraction.md) | Keyword extraction pipeline |
| [UX Design](./design/ux.md) | UI/UX design |
| [Testing Strategy](./testing/strategy.md) | Test strategy |
