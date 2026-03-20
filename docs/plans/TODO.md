# LexiconArxiv — TODO

Tracked enhancement backlog. Items are grouped by priority and area.

---

## High Priority

### Stub Enrichment & Corpus Gaps
- [ ] **Enrich high-value stubs** — 23,960 stubs cited by 20+ core papers have zero metadata (no title, abstract, authors). Enrich via OpenAlex by identifier (DOI/arXiv/OpenAlex ID). Target: top 25K stubs.
- [ ] **Resolve TITLE: stubs** — Many stubs have `identifier_type=title` with raw title strings from GROBID. Search OpenAlex by title to find DOI/metadata and merge.
- [ ] **Corpus gap dashboard** — Dashboard section showing: top 100 most-cited stubs (= most-cited papers NOT in corpus), venues most referenced but not collected, stubs that could be promoted.
- [ ] **Stub → core promotion** — When incremental collection adds a paper matching an existing stub, preserve the stub's `cited_by` data on the promoted paper. Verify dedup handles this correctly.

### Advanced Retrieval Pipeline
- [ ] **Multi-vector prefetch** — Search 3+ section vectors per query (structured-abstract + section-method + section-task), fuse with RRF. Currently only 1 dense vector used per search.
- [ ] **Query intent detection** — Auto-detect target section from query ("papers using X" → method, "papers about X" → task). Keyword heuristics first, optional LLM.
- [ ] **Cross-encoder reranking** — Rerank top-50 with Qwen3-Reranker-8B via Ollama. Pull model: `ollama pull dengcao/Qwen3-Reranker-8B`. Expected +5-15% nDCG@10.
- [ ] **Citation-aware score boosting** — Multiply RRF score by `alpha*score + beta*log(citations) + gamma*pagerank`. Pure post-processing on existing data.
- [ ] **MMR diversity** — Maximal Marginal Relevance to prevent redundant results. Client-side post-processing.
- [ ] **Venue name normalization** — "ICLR 2025 Poster" should match filter "ICLR". Add `venue_canonical` field or use substring matching.

### Advanced Query Processing
- [ ] **HyDE** — Generate hypothetical abstract via LLM, embed that instead of raw query. +5-25% recall on vague queries. Adds ~500ms.
- [ ] **RAG-Fusion** — Generate 3-5 query variants via LLM, search each, fuse with RRF. +8-10% accuracy. Qdrant prefetch supports natively.
- [ ] **Query decomposition** — "BERT vs GPT for code" → 3 sub-queries targeting different section vectors.

---

## Medium Priority

### Stub Vectors & Search
- [ ] **Embed enriched stubs** — Once high-value stubs have abstracts, embed them (dense + BM25). Enables cross-boundary similarity and makes stubs discoverable in search.
- [ ] **BM25 on enriched stubs** — Stubs with titles/abstracts get BM25 vectors so users can find cited papers even if not in core corpus.

### Retrieval Enhancements
- [ ] **SPLADE sparse vectors** — Replace BM25 with learned sparse retrieval (SPLADE++). +10-20% over BM25 but requires re-indexing.
- [ ] **Neural PRF (2-pass)** — Average top-5 result vectors with query for refined second pass. +26% MAP.
- [ ] **Adaptive weighted RRF** — Dynamically weight dense vs BM25 based on query characteristics.

### Configurable Pipeline
- [ ] **RetrievalConfig dataclass** — Toggle each technique on/off via API parameters and server defaults.
- [ ] **Pipeline presets** — "Fast" (default), "Quality" (+ HyDE + reranker), "Comprehensive" (+ RAG-Fusion + MMR).
- [ ] **Pipeline info in response** — Return which stages were applied, detected intent, vectors searched, etc.

---

## Lower Priority

### Data Quality
- [ ] **Stub dedup audit** — Multiple stubs may refer to the same paper via different identifiers. Verify merge logic is comprehensive.
- [ ] **Zero-title stubs investigation** — Investigate why `enrich-8-metadata-by-stub-via-openalex` didn't populate titles. May need to re-run or fix the enricher.

### Search UX
- [ ] **Export (BibTeX/CSV/JSON)** — PRD Section 5.4 feature. Export search results for use in papers.
- [ ] **Saved queries & alerts** — PRD Section 5.4 feature. Save searches and get notified on new matching papers.

### Advanced Techniques
- [ ] **GRF (Generative Relevance Feedback)** — More sophisticated than HyDE. +17-24% nDCG@10 but higher latency.
- [ ] **ColBERT late interaction** — Overkill at 145K scale when cross-encoder reranking is available.

---

## Completed

- [x] Phase 1: Embedding Pipeline (section-level, 9 dense + BM25)
- [x] Phase 2: Search API + Web UI (hybrid search, RRF)
- [x] Phase 3: MCP Server (6 tools)
- [x] Phase 4: On-demand Retrieval (arXiv + OpenAlex)
- [x] Phase 5: Trends & Notable Papers (metrics + UMAP/HDBSCAN)
- [x] Phase 6: Semantic Similarity Graph (5 typed edge types)
- [x] Data Health Dashboard with pipeline alerting
- [x] Keyword autocomplete
- [x] Shared navigation, page titles, venue dropdown, landing state
- [x] Incremental pipeline updated for embedding/similarity/clustering
- [x] Multi-label sentence deduplication in structured-abstract
- [x] Title included in BM25 + dense vectors
- [x] Critical incremental update fixes (HasVectorCondition, partial chunk recovery)
