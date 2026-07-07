# Qdrant payload catalog

**Scope:** every payload field written to points in `lexicon_arxiv_v3` (production collection). For each field: what it is, which pipeline stage writes it, the current data-quality expectation, and whether Qdrant has a payload index on it. Verified 2026-07-06 against the live collection.

**How to use this document:**

- Writing a new bulk-scroll query? Check §"Index status" to make sure your filter's key is indexed — otherwise your query is a 60 s scroll_by_id timeout waiting to happen ([`../runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) §Payload indices).
- Debugging why a field is empty? Check §"Field × Stage matrix" to see which stage is supposed to fill it.
- Writing a DQ check? Check §"DQ rules by field" for the current contract.
- The Postgres schema in [`../architecture/data_model.md`](../architecture/data_model.md) §4 is a design reference from an earlier design — production storage is Qdrant-only; that document's §5 payload table is a subset of this catalog.

---

## 1. Field catalog

Fields are grouped by role. Each entry: type · source(s) that write it · description.

### 1.1 Identifiers

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `openalex_id` | `str` (`W...`) | OpenAlex crawler; P1 enrich; P2/P3 injection | Primary cross-source key. Stripped of the `https://openalex.org/` prefix at write time (see `snapshot/extractor.py::_norm_openalex_id`). |
| `doi` | `str` (lowercase) | OpenAlex/CrossRef/S2 crawlers; P1 enrich | Normalized: prefix stripped, lowercased (`snapshot/extractor.py::_norm_doi`). Unique within corpus per the DOI dedup rule. |
| `arxiv_id` | `str` (e.g. `2405.12345`) | ArXiv crawler; extracted from `ids.arxiv` or DOI in P1 | Set for arXiv preprints. Used by [`arxiv-download`](../pipelines/data_collection.md) and by the arxiv-tail incremental phase. |
| `acl_id` | `str` | ACL Anthology crawler | ACL Anthology paper ID. |
| `source_id` | `str` | Crawler (bookkeeping) | Original per-source id (e.g. `dblp:conf/nips/foo`). Legacy field — most queries prefer `openalex_id`. |
| `alternate_identifiers` | `dict` | P2 promotion (`writer.batch_promote_stubs_from_snapshot`) | Bag of secondary IDs preserved from a stub during promotion. |
| `openalex_source_id` | `str` (`S...`) | P1 enrich (added 2026-07-06) | The venue's OpenAlex Source ID (from `primary_location.source.id`). Used by [`retrofit-tier-from-source-id`](../../src/cli/commands/snapshot.py) to backfill `tier` on P2/P3-injected points that never went through a venue-first crawler. |

### 1.2 Content

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `title` | `str` | Crawler / snapshot extractor | Paper title. Required field. |
| `abstract` | `str` | Crawler; enrich-6 abstracts; P1 enrich | Body abstract. Empty string means "we tried and none exists" (distinct from missing key = "never tried"). |
| `authors` | `list[dict]` | Crawler; P1 enrich | `[{"display_name": "..."}, ...]`. First-author surname used for corroboration matching. |
| `venue` | `str` (text-indexed) | Crawler; P1 enrich from `primary_location.source.display_name` | Human-readable venue name. |
| `year` | `int` | Crawler; P1 enrich from `publication_year` | Publication year. Indexed 2026-07-06 to enable year-bucket chronological chunking. |
| `publication_date` | `str` (`YYYY-MM-DD`) | Crawler; P1 enrich from `publication_date` | Full publication date. |
| `month` | `int` | Crawler | Publication month; parallel to `year`. |
| `categories` | `list[str]` | Crawler | Source-specific categories (e.g. arXiv subject categories). |

### 1.3 Classification

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `type` | `keyword` (`article`, `preprint`, `book`, `peer-review`, `editorial`, `letter`, `erratum`, ...) | P1 enrich | **The OpenAlex work type.** Indexed 2026-07-06. Load-bearing for [Wave 4b non-article cleanup](../refactoring/2026-07-04-code-overhaul-plan.md). |
| `paper_type` | `keyword` | Crawler | Legacy internal classification (`method`, `dataset`, `survey`, `benchmark`, `analysis`, `application`, `position`, `demo`). Distinct from `type` above. |
| `venue_type` | `keyword` | Crawler | `conference` / `workshop` / `journal` / `preprint`. |
| `tier` | `integer` | OpenAlex crawler (`tier=venue.tier` at write time). **Not** set by P2/P3 injections. | 0/1/2/null. Used by `label-abstracts --priority-tier`. Retrofit for P2/P3 via `retrofit-tier-from-source-id` after `openalex_source_id` backfill. |
| `is_core` | `bool` | OpenAlex crawler | True for Tier 0/1/2 venue papers. |
| `is_stub` | `bool` | Reference resolver (`resolve-refs-to-papers`); P2 promotion sets to `False` | True = a placeholder point created because another paper cited a work not yet in corpus. Indexed. 6.0M of 6.2M points are stubs. |
| `language` | `str` (ISO 639-1) | P1 enrich | Language code (`en`, `zh`, ...). |
| `is_preprint` | `bool` | Crawler | Legacy flag; `type = "preprint"` in the newer OpenAlex-derived record. |

### 1.4 Bibliometrics

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `cited_by_count` | `int` | Crawler / P1 enrich from OpenAlex `cited_by_count` | Global (OpenAlex-wide) citation count. |
| `citation_count` | `int` | Crawler (S2, legacy) | Alternative citation count from Semantic Scholar. Prefer `cited_by_count` when both exist. |
| `cited_by_count_internal` | `int` | `build-cited-by` graph asset | Count of papers **inside the corpus** that cite this paper. |
| `cited_by` | `list[str]` | `build-cited-by` graph asset | Internal `point_id`s of papers that cite this one. Preserved on stub promotion. |
| `referenced_works` | `list[str]` (OpenAlex `W...`) | OpenAlex crawler; `enrich-4-refs-by-doi-via-s2`; `enrich-2-refs-by-doi-via-crossref` | Outgoing citation targets. Feeds the citation graph and the ref-based stub creation path. |
| `fwci` | `float` | P1 enrich | Field-Weighted Citation Impact (OpenAlex; 1.0 = field average). Useful for priority-based labeling (fwci ≥ 5 keeps 47 % of P2/P3 subset). |
| `citation_normalized_percentile` | `dict` | P1 enrich | `{value: 0.0-1.0, is_in_top_1_percent: bool, is_in_top_10_percent: bool}`. Complementary to `fwci`. |
| `counts_by_year` | `list[dict]` | P1 enrich | `[{year, cited_by_count}, ...]` — annual citation trajectory. |

### 1.5 Semantic classification (OpenAlex)

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `concepts` | `list[dict]` | P1 enrich | OpenAlex concept classifiers (legacy, being deprecated by Topics). |
| `topics` | `list[dict]` | P1 enrich | Newer OpenAlex Topics classification. |
| `primary_topic` | `dict` | P1 enrich | `{id, display_name, field, subfield, domain}`. Used for corpus AI-relevance filtering — the sample paper we found in the 2026-07-06 audit had `primary_topic = "Health Sciences Research"` even though it was P3-injected. |
| `mesh` | `list[dict]` | P1 enrich | MeSH terms (biomedical papers). |
| `sustainable_development_goals` | `list[dict]` | P1 enrich | OpenAlex SDG classification. |
| `funders` | `list[dict]` | P1 enrich | Grant/funding metadata. |
| `institutions` | `list[dict]` | P1 enrich | Institution affiliations. |
| `orcid_map` | `dict[author→ORCID]` | P1 enrich | ORCID lookup by author display_name. |

### 1.6 Keyword extraction

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `keywords` | `list[str]` | `extract-keywords` (Step 5) | Flat keyword list. Production uses regex + KeyBERT (no LLM at bulk scale per Path B). |
| `keywords_source` | `keyword` | `extract-keywords` | Pipe-delimited backend id: `"regex\|keybert"`. Historical: `"gemini\|judge"` (removed in v0.12), `"ollama"` (Ollama chat retired from pipeline; dev-laptop only). |
| `keywords_structured` | `dict` | `extract-keywords` | Categorized: `{task, method, model, domain, dataset, contribution_type, modality}`. |

### 1.7 Labeled abstract structure

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `abstract_structure` | `dict` | `label-abstracts` (Step 6) | Sentence role classification: `{task, domain, background, approach, method, result, contribution}`. Truncated to first 25 sentences at write time (`labeler.py::MAX_SENTENCES_TO_LABEL`, 2026-07-06). |
| `abstract_structure_source` | `keyword` (`vllm`, `ollama`, `none`) | `label-abstracts` | Which backend produced the current label. Indexed 2026-07-06 to enable Ollama-partial re-label pass (Wave 4b Issue B). |

### 1.8 Provenance / bookkeeping

Fields that record *how* a point got into the corpus and *when*. These are what the enrichment pipeline and post-hoc analytics use to slice the corpus.

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `fetched_at` | `datetime` | Crawler (`paper.fetched_at`) | ISO timestamp at crawl. **Only ~178 K of 6.2 M points have this** — P2/P3 injections don't write it. Indexed. Used by `--recent-days`. See Wave 1e-quater backfill plan. |
| `enriched_at` | `datetime` | Enrichers (`enrich-*`) | Timestamp of last successful enrichment. |
| `code_enriched_at` | `datetime` | `enrich-code-repos` | Separate timestamp for code-repo enrichment. |
| `code_repositories` | `list[dict]` | `enrich-code-repos` | GitHub/etc. repos linked to the paper. |
| `injected_from_snapshot` | `bool` | P3 injection (`writer.batch_inject_papers`) | True on every P3-injected point. Indexed 2026-07-06. |
| `injection_path` | `keyword` | P3 injection | Which anchor path caused injection (`anchor_cited`, `anchor_cites`, ...). |
| `injected_at` | `datetime` | P3 injection | Timestamp of P3 injection. |
| `snapshot_filled_at` | `datetime` | P2 promotion + P3 injection | Snapshot date used for the write. Indexed 2026-07-06. Load-bearing for chronological chunking and `fetched_at` backfill. |
| `promoted_from_stub` | `bool` | P2 promotion | True if this point was formerly a stub. |
| `promoted_at` | `datetime` | P2 promotion | Timestamp of stub → real promotion. |

### 1.9 Analytics / search

Fields added by later pipeline stages (embedding, similarity graph, clustering, notable-paper scoring). Not present on freshly-crawled points.

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `similar_papers` | `dict` | `compute-similarity` | Pre-computed similar paper IDs with cosine scores. |
| `cluster_id` | `int` | `topic-clusters` | Cluster assignment from HDBSCAN (or replacement). |
| `umap_x`, `umap_y` | `float` | `topic-clusters` | 2D UMAP coordinates for the notable-papers map UI. |
| `pagerank` | `float` | `citation-graph` | PageRank score over the internal citation graph. |
| `notability_score` | `float` | `notable-papers` | Composite score used for the notable-papers dashboard. |

### 1.10 Access URLs

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `pdf_url` | `str` | Crawler | Direct PDF URL. |
| `abstract_url` | `str` | Crawler | Landing page. |
| `best_oa_pdf_url` | `str` | P1 enrich (from `best_oa_location.pdf_url`) | Best open-access PDF URL. |
| `open_access` | `dict` | P1 enrich | `{is_oa, oa_status, any_repository_has_fulltext, oa_url}`. |

### 1.11 Legacy / raw

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `raw_data` | `dict` | Crawler | The unparsed source record. Kept for debug; downstream code should not depend on it. |
| `field` | `keyword` | Crawler (design-time only) | Field bucket (NLP/ML/AI/DM/IR/Web/Legal). Not consistently populated on the live collection — prefer `primary_topic.field` from OpenAlex. |

---

## 2. Field × Stage matrix

Reading the matrix: `W` = writes the field for the first time · `U` = updates (overwrites) an existing value · `–` = does not touch this field.

Stages (columns) in pipeline order:

- **Crawler** — venue crawlers (OpenAlex/ACL/DBLP/OpenReview/ACM/AAAI)
- **P1** — `enrich-corpus-fields` (snapshot metadata backfill on existing points)
- **P2** — `resolve-stubs-from-snapshot` (stub → real promotion)
- **P3** — `discover-corpus-gaps` (net-new paper injection)
- **E-abs** — `enrich-6-abstracts-by-doi-via-openalex`
- **E-ref** — `enrich-4-refs-by-doi-via-s2` + `enrich-2-refs-by-doi-via-crossref`
- **KW** — `extract-keywords` (Step 5)
- **LAB** — `label-abstracts` (Step 6)
- **REF** — `resolve-refs-to-papers` (Step 7; creates stubs from refs not yet in corpus)
- **STB** — `enrich-8-metadata-by-stub-via-openalex`
- **CB** — `build-cited-by`
- **EMB** — `embed-papers`
- **SIM** — `compute-similarity`
- **CG** — `citation-graph` (pagerank)
- **CLU** — `topic-clusters`

| Field | Crawler | P1 | P2 | P3 | E-abs | E-ref | KW | LAB | REF | STB | CB | EMB | SIM | CG | CLU |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openalex_id` | W | U | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `doi` | W | U | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `arxiv_id` | W | U | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `openalex_source_id` | – | W (2026-07-06+) | – | W | – | – | – | – | – | – | – | – | – | – | – |
| `title`, `authors`, `venue` | W | U | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `year`, `publication_date` | W | U | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `type` | – | W | – | W | – | – | – | – | – | – | – | – | – | – | – |
| `tier` | W | – | – | – | – | – | – | – | – | – | – | – | – | – | – |
| `is_core` | W | – | – | – | – | – | – | – | – | – | – | – | – | – | – |
| `is_stub` | – | – | U (→false) | W (=false) | – | – | – | – | W (=true) | U | – | – | – | – | – |
| `abstract` | W | U | – | W | W/U | – | – | – | – | U | – | – | – | – | – |
| `cited_by_count`, `fwci`, `citation_normalized_percentile` | – | W | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `concepts`, `topics`, `primary_topic`, `mesh`, `sdgs`, `funders`, `institutions`, `orcid_map` | – | W | – | W | – | – | – | – | – | U | – | – | – | – | – |
| `referenced_works` | W (OA crawl) | U | – | W | – | W/U | – | – | – | U | – | – | – | – | – |
| `keywords`, `keywords_source`, `keywords_structured` | – | – | – | – | – | – | W | – | – | – | – | – | – | – | – |
| `abstract_structure`, `abstract_structure_source` | – | – | – | – | – | – | – | W | – | – | – | – | – | – | – |
| `cited_by`, `cited_by_count_internal` | – | – | preserved | – | – | – | – | – | – | – | W | – | – | – | – |
| `similar_papers` | – | – | – | – | – | – | – | – | – | – | – | – | W | – | – |
| `pagerank` | – | – | – | – | – | – | – | – | – | – | – | – | – | W | – |
| `cluster_id`, `umap_x`, `umap_y` | – | – | – | – | – | – | – | – | – | – | – | – | – | – | W |
| `fetched_at` | W | – | – | – | – | – | – | – | – | – | – | – | – | – | – |
| `injected_from_snapshot`, `injection_path`, `injected_at` | – | – | – | W | – | – | – | – | – | – | – | – | – | – | – |
| `promoted_from_stub`, `promoted_at` | – | – | W | – | – | – | – | – | – | – | – | – | – | – | – |
| `snapshot_filled_at` | – | – | W | W | – | – | – | – | – | – | – | – | – | – | – |
| `enriched_at` | – | – | – | – | U | U | – | – | – | – | – | – | – | – | – |

Empty cells are literal `–` (not a formatting quirk) — the stage does not write that field.

---

## 3. DQ rules by field

Only fields with a currently-active DQ rule are listed. Rules in `src/core/pipeline/dq.py` unless noted otherwise.

| Field | Rule | Severity | Notes |
|---|---|---|---|
| `title` | Required non-empty on every real paper (`is_stub=False`). | ERROR (blocking) | Any real paper without a title is a bug — either a stub that wasn't cleaned up or a crawler bug. |
| `abstract` | Required non-empty on every P2/P3 paper (`snapshot_filled_at IS NOT NULL`) after post-bootstrap catchup. Empty-string abstracts count as absent per the 2026-07-05 fix. | ERROR (blocking) | Enables search on the abstract vector. |
| `abstract_structure` | Required on any real paper where `abstract IS NOT NULL AND len(abstract) > 0`. | ERROR (blocking) | Enables the section-* vectors and structured-abstract fallback. |
| `keywords` | Required non-empty on any real paper where `abstract IS NOT NULL`. | ERROR (blocking) | Enables keyword-based recall paths. |
| `openalex_id` | Required on every P2/P3 point. | ERROR | Any snapshot-derived point without an `openalex_id` is a P2/P3 writer bug. |
| `type` | Should be in `{article, preprint, conference-paper, dissertation, book-chapter}` when set. Non-article types (`book`, `peer-review`, `editorial`, `letter`, `erratum`, `retraction`, `other`) drive the [Wave 4b cleanup](../refactoring/2026-07-04-code-overhaul-plan.md). | WARN | See [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §P3 data-quality gap. |
| `cited_by_count` | If set, must be `≥ 0`. | ERROR | Sanity check. |
| `is_stub` | Every point must have this field set. | ERROR | Missing = the point was written by a non-standard path. |
| `referenced_works` | Empty list is fine; must be a list if present. | ERROR (type check) | – |
| `fetched_at` | If set, must be a valid ISO datetime. | ERROR (type check) | Not required-present (P2/P3 don't write it — see backfill plan). |

**Corpus-level checks** (not per-field):

- `nonarticle_type_share` (planned, Wave 4b-6) — WARN if `type IN {book, peer-review, editorial, ...}` exceeds 1 % of the corpus.
- `ollama_labeled_share` (planned, Wave 4b-6) — WARN if `abstract_structure_source = "ollama"` exceeds 5 % of the corpus after catchup completes.
- Existing checks in `dq.py`: `missing_abstract_share`, `missing_structure_share`, `missing_keywords_share`, `missing_similarity_share`, `search_health`, etc. — see [`../pipelines/*.md`](../pipelines/) for per-stage detail.

---

## 4. Index status

Full source of truth is `curl http://localhost:6333/collections/lexicon_arxiv_v3 | jq .result.payload_schema`. Snapshot as of 2026-07-06:

| Field | Type | Points populated | Added |
|---|---|---:|---|
| `fetched_at` | datetime | 178 705 | pre-existing |
| `source_id` | keyword | 178 705 | pre-existing |
| `is_stub` | bool | 6 033 943 | pre-existing |
| `doi` | keyword | 4 509 664 | pre-existing |
| `openalex_id` | keyword | 4 654 370 | pre-existing |
| `arxiv_id` | keyword | 105 777 | pre-existing |
| `venue` | text | 4 292 757 | pre-existing |
| `abstract_structure_source` | keyword | 240 020 | 2026-07-06 (batch 1) |
| `injected_from_snapshot` | bool | 2 590 221 | 2026-07-06 (batch 1) |
| `snapshot_filled_at` | datetime | 4 745 799 | 2026-07-06 (batch 1) |
| `year` | integer | 4 776 715 | 2026-07-06 (batch 1) |
| `type` | keyword | 4 600 242 | 2026-07-06 (batch 1) |
| `promoted_from_stub` | bool | 974 457 | 2026-07-06 (batch 2 — Wave 4c gate) |
| `tier` | integer | 3 056 | 2026-07-06 (batch 2 — only 178 K OpenAlex venue-crawled papers carry it) |
| `graph_indexed` | bool | 1 809 430 | 2026-07-07 (Wave 1e-sexies — Step 9 `build-cited-by --incremental` filter) |

**Rule** (see [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Third rule): any new bulk-scroll filter must use only fields from this list. Adding a filter on an unindexed payload field at 6.2 M-scale is a deterministic 60 s server-side timeout.

If you need a new indexed field, add the online-build call in [`../runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) §Payload indices and update this table in the same PR.

---

## 5. Common queries

Copy-paste recipes for the queries this catalog exists to unblock. All use only indexed fields.

**Papers needing labeling (bulk backlog)**

```python
must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract_structure_source"))]
must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
```

**Ollama-labeled subset (candidates for vLLM re-label)**

```python
must=[models.FieldCondition(key="abstract_structure_source", match=models.MatchValue(value="ollama"))]
```

**Year-bucket chronological chunking**

```python
must=[models.FieldCondition(key="year", range=models.Range(gte=2020, lt=2023))]
```

**P2/P3-injected subset (Wave 4b type-cleanup target)**

```python
must=[models.FieldCondition(key="injected_from_snapshot", match=models.MatchValue(value=True))]
```

**Non-article cleanup candidates**

```python
must=[models.FieldCondition(key="type", match=models.MatchAny(any=["book", "peer-review", "editorial", "letter", "erratum"]))]
```

**Recently-crawled papers** (still only reaches the ~178 K papers that have `fetched_at`)

```python
must=[models.FieldCondition(key="fetched_at", range=models.DatetimeRange(gte="2026-06-05"))]
```

**Recently snapshot-filled papers** (reaches P2/P3 too — use this instead of `fetched_at` when you want catchup coverage)

```python
must=[models.FieldCondition(key="snapshot_filled_at", range=models.DatetimeRange(gte="2026-06-05"))]
```

---

## 6. See also

- [`../runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) — CPU tuning + payload index create/verify runbook.
- [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) — Three-rule design guide for bulk vs incremental phases; §Third rule explains why indexing is a correctness precondition at corpus scale.
- [`../architecture/data_model.md`](../architecture/data_model.md) §5 — Original design-time schema. Payload subset there is a historical snapshot; this catalog supersedes it.
- [`../pipelines/`](../pipelines/) — per-stage runbooks. Look up a field's write-column in §2 to jump to the right one.
- [`../refactoring/2026-07-04-code-overhaul-plan.md`](../refactoring/2026-07-04-code-overhaul-plan.md) Wave 1e / 4b — the follow-up items that would move this catalog from "descriptive" to "enforced by CI".
