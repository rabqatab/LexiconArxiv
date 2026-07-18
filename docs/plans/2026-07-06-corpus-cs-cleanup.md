# Corpus CS-relevance cleanup (Wave 4c)

**Status:** proposed 2026-07-06 · author: 2026-07-06 corpus audit · scope: destructive · trigger: post-catchup-stable

**One-line goal:** remove the ~2.4 M non-CS-adjacent points from the production collection so this becomes a real AI/NLP research corpus, and add a durable filter at the P2/P3 boundary so the next quarterly bootstrap does not re-introduce the pollution.

---

## 1. Why we're doing this

The 2026-07-06 audit sampled 100 000 non-stub real papers by `primary_topic.field` and found the corpus is **only 32.6 % AI-adjacent**. Two-thirds of the current 3.56 M "real paper" points are cross-domain references or anchor-adjacency artifacts from P2/P3 that leak into the vector search index, similarity graph, and topic clusters even though nobody would ever want them in an AI-research-focused MCP tool.

**Root cause** (see [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §P3 data-quality gap): `discover_corpus_gaps` (P3) and `resolve-stubs-from-snapshot` (P2) both operate on any snapshot work matching the anchor + concept criterion, with no `primary_topic` gate. Every AI paper cites ~50 cross-domain works (Nature papers, biology methods, physics simulation, medical trials, econometric analyses), and the pipeline currently pulls all of them into the "papers" collection instead of leaving them as stubs.

**Why now:** the 2026-07-06 investigation on labeling ETA revealed the corpus is old-skewed (72 % pre-2015) mostly because of these injections. The labeling backlog is 3.5 M papers; if 2.4 M of those are non-CS, we would spend weeks of vLLM budget labeling papers no one will ever search for. Deleting first shrinks the labeling backlog to ~1.16 M, which is actually feasible.

---

## 2. Policy: P3 whitelist

**Keep only papers whose `primary_topic.field.display_name` is in this whitelist OR whose `primary_topic.subfield.display_name` is `"Language and Linguistics"`:**

```
KEEP_FIELDS = {
    "Computer Science",
    "Mathematics",
    "Decision Sciences",     # statistics, OR, operational
    "Neuroscience",          # brain-inspired models, cog sci
    "Psychology",            # cognitive psychology, psycholinguistics
}
KEEP_SUBFIELDS = {
    "Language and Linguistics",  # from Arts and Humanities field
}
```

Delete everything else. Papers with **no `primary_topic` at all** (~19 K estimated) are deleted with the pollution — they are almost entirely P2/P3 injections that even OpenAlex couldn't classify. If we want to preserve edge cases we can whitelist by identifier later.

**Estimated blast (100 K sample × 3.56 M corpus scaling, ±0.5 %):**

| Bucket | Papers | Share |
|---|---:|---:|
| KEEP: Computer Science | ~591 K | 16.6 % |
| KEEP: Neuroscience | ~239 K | 6.7 % |
| KEEP: Psychology | ~181 K | 5.1 % |
| KEEP: Decision Sciences | ~80 K | 2.2 % |
| KEEP: Mathematics | ~54 K | 1.5 % |
| KEEP: Arts and Humanities (Linguistics subfield only) | ~17 K | 0.5 % |
| **KEEP total** | **~1.16 M** | **32.6 %** |
| DELETE: Medicine | ~485 K | 13.6 % |
| DELETE: Engineering | ~413 K | 11.6 % |
| DELETE: Biochemistry, Genetics and Molecular Biology | ~401 K | 11.2 % |
| DELETE: Physics and Astronomy | ~199 K | 5.6 % |
| DELETE: Social Sciences (non-linguistics) | ~186 K | 5.2 % |
| DELETE: Environmental Science | ~154 K | 4.3 % |
| DELETE: Business, Management, Accounting | ~98 K | 2.8 % |
| DELETE: Materials Science, Chemistry, Economics, Earth Sciences, Immunology, Agricultural, Health Professions | ~250 K | 7.0 % |
| DELETE: other (< 1 % each field), no-topic | ~193 K | 5.4 % |
| **DELETE total** | **~2.38 M** | **66.9 %** |
| no-topic (also deleted) | ~19 K | 0.5 % |

Downstream corpus after cleanup: **~1.16 M non-stub real papers** (from 3.56 M).

Non-CS **stubs** (~2.5 M is_stub=True) are left in place — they are already excluded from search (`src/core/search/service.py:114`) and continue to serve the citation-graph "cited by NeurIPS 2025 paper X" link even if X cited a Nature paper.

---

## 3. Plan

### Phase 1 — dry-run + reversibility rehearsal (day 1)

- [ ] **Task 1.1: Count with production filter.** Run `scripts/analytics/count_by_topic.py` (new — see Task 4.1) with the exact P3 whitelist, produce a per-field / per-year / per-provenance breakdown. Compare against §2 estimates; the counts should be within ±0.5 %. Any big divergence means the sampling was biased and we investigate before deleting.
- [ ] **Task 1.2: Snapshot the point-id list of everything about to be deleted.** Save to `snapshots/2026-07-06-cs-cleanup/delete-ids.jsonl` (one openalex_id per line + primary_topic + venue + title). This is our recovery map — if we later regret the deletion for a specific field, we can re-fetch these ~2.4 M point_ids from the OpenAlex snapshot. Not committed to git (`docs/plans/TODO.md` [no-push-research-reports rule]).
- [ ] **Task 1.3: Search-quality rehearsal.** Run 20 representative queries against a `_read_replica` collection where we've PATCH-ed a filter that excludes the delete set (`must_not: primary_topic.field NOT IN whitelist`). Confirm no degradation on the queries an NLP researcher actually cares about; confirm the queries that USED to surface cross-domain papers now surface CS results instead. Log all 20 results before/after.

### Phase 2 — durable filter at the source (day 2, blocks Phase 3)

- [ ] **Task 2.1: Add `primary_topic` filter to P3.** `src/core/snapshot/phase3_gap_discovery.py::process_one` — after the anchor + concept check, before the write, gate on `primary_topic.field IN KEEP_FIELDS OR primary_topic.subfield == "Language and Linguistics"`. Log the count of rejected-by-topic per run. This is the durability step: the next quarterly bootstrap will not re-inject what we just deleted.
- [ ] **Task 2.2: Add `primary_topic` filter to P2.** `src/core/snapshot/writer.py::batch_promote_stubs_from_snapshot` — same gate. Non-matching stubs stay as stubs, not real papers.
- [ ] **Task 2.3: Add DQ warn-checks.** `src/core/pipeline/dq.py`:
    - `nontarget_topic_share()` — WARN if non-whitelist field share exceeds 5 % of the non-stub corpus (baseline post-cleanup: near 0 %; any drift means Task 2.1 / 2.2 regressed).
    - `no_primary_topic_share()` — WARN if points with no `primary_topic` exceed 1 % of the non-stub corpus.

### Phase 3 — delete (day 3, one-shot, irreversible)

- [ ] **Task 3.1: Delete non-CS non-stubs via Qdrant filter delete.** One `POST /points/delete` per year bucket (2010, 2015, 2020, current) to keep the operation observable and interruptible. Delete filter:
    ```
    must=[non-stub AND (primary_topic missing OR primary_topic.field NOT IN KEEP_FIELDS)]
    must_not=[primary_topic.subfield == "Language and Linguistics"]
    ```
- [ ] **Task 3.2: Cleanup dangling references** (secondary; the search doesn't error on stale IDs but the `cited_by` count is misleading). For each remaining paper, remove point_ids from `cited_by` and `similar_papers` lists that no longer exist. Iterate in 10 K-point batches with the standard `_retry_qdrant_call`.
- [ ] **Task 3.3: Recompute analytics.** `pagerank` and `cluster_id` change once the graph shrinks by a third; enqueue the citation-graph and topic-clusters assets to rerun. `notable-papers` scoring recomputes on top.
- [ ] **Task 3.4: DQ full-corpus check.** Run the full DQ suite. Every `_share` metric shifts significantly — new baselines get recorded in DQ output for future comparison.
- [ ] **Task 3.5: MCP sanity.** Confirm every MCP tool (`search_papers`, `get_paper`, `research_topic`, `get_similar_papers`, `expand_search`, `get_citations`, `get_corpus_stats`) returns reasonable results on 3 canonical queries per tool.

### Phase 4 — bulk labeling on the shrunk backlog (day 4+)

The labeling backlog was ~3.5 M unlabeled non-stub real papers. After Phase 3 it should be **~950 K – 1 M** (majority of the KEEP set is unlabeled). At the current vLLM production rate this is now weeks of work, not months.

- [ ] **Task 4.1: Chronological chunking runs.** With `year` indexed (2026-07-06), submit sparkq jobs bucketed by year. Prefer newest → oldest to prioritise search relevance:
    - 2025-2026 (small, fast smoke test)
    - 2020-2024
    - 2015-2019
    - 2010-2014
    - pre-2010 (last — most likely to be foundational classics)
- [ ] **Task 4.2: Ollama-partial re-label pass.** After the pure-catchup work, filter to `abstract_structure_source = "ollama"` (240 K papers today; will be smaller post-cleanup) and re-label with vLLM for consistency.

---

## 4. Reversibility

**Point deletion is irreversible in Qdrant.** Recovery paths after Phase 3, in order of preference:

1. **From the OpenAlex snapshot**: every deleted point has an `openalex_id`; re-run P1 backfill on the recovery list to re-inject them (requires temporarily relaxing the P3 filter).
2. **From `snapshots/2026-07-06-cs-cleanup/delete-ids.jsonl`** (Task 1.2): explicit re-inject by ID, no snapshot re-scan required.
3. **From Qdrant snapshot backup**: only viable if we take one before Phase 3 (add this as Task 2.4 if we want a fully atomic rollback).

Sustainable filter (Phase 2) means recovery will re-encounter the same P2/P3 gate — if we recover, we're accepting that specific ID over the policy.

---

## 5. Definition of done

- Non-stub real paper count drops from ~3.56 M to ~1.16 M (±5 %).
- `primary_topic.field` distribution on the remaining corpus is dominated by CS + adjacent (~90 % of the sample; the residual is the ~10 % that was already CS-adjacent but the count naturally shifts as denominators change).
- All MCP tools pass canonical queries (Task 3.5).
- New DQ warn-checks (`nontarget_topic_share`, `no_primary_topic_share`) are green.
- P2 and P3 code paths both apply the `KEEP_FIELDS` + linguistics-subfield gate (Task 2.1 / 2.2), unit-tested against sample OpenAlex records that include one keep, one delete, one no-topic.
- [`docs/reference/qdrant-payload-catalog.md`](../reference/qdrant-payload-catalog.md) DQ section updated with the two new checks and the whitelist definition.

---

## 6. Out of scope

- **Stubs**: not touched. They stay is_stub=True, still excluded from search, still needed for citation-graph edges. If a stub is enriched later (Step 8) and its topic is non-CS, it stays as a stub — the P2 gate (Task 2.2) prevents promotion to real paper, which is enough.
- **Legacy tier=0/1/2 papers**: the 178 K tier venue papers we already have are the original crawler seed and mostly CS-adjacent by construction; they are inside the KEEP set naturally.
- **Ollama re-labeling for non-CS papers**: those get deleted, so no need to re-label them (was Wave 4b Issue B, now moot for the deleted subset).
- **Year cutoff**: the P3 whitelist filter makes year cutoffs unnecessary. Pre-2010 CS papers (word2vec pre-history, LDA, CRF, HMM, PageRank, TREC IR) are all preserved because they're `field="Computer Science"` regardless of year.

---

## 7. Cross-references

- Trigger doc: [`../design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §P3 data-quality gap + §Third rule.
- Sustainable filter design: [`../refactoring/2026-07-04-code-overhaul-plan.md`](../refactoring/2026-07-04-code-overhaul-plan.md) Wave 4b (Type filter — related but different criterion, both apply) and Wave 4c (this plan when merged).
- Payload catalog updated as a side-effect: [`../reference/qdrant-payload-catalog.md`](../reference/qdrant-payload-catalog.md).
- Live backlog entry: [`TODO.md`](TODO.md) will get a "Corpus quality audit — cross-provenance review" item update pointing here.

---

## 8. Execution record — 2026-07-08/09 (Option B: demote, not delete)

**Decision change from the original plan:** the user chose **demote-to-stub over hard delete** after Phase 1 measurement showed hard delete reclaims only ~35 GB (15% of 241 GB) — storage was not the real driver, and demotion preserves citation-graph edges + full reversibility (re-promote) while achieving identical search cleanup (stubs are excluded from search).

**Two deviations from the plan, both toward safety:**
1. **Crawler-provenance protection.** The delete/demote filter is scoped to `injected_from_snapshot OR promoted_from_stub`. Phase 1 sampling found ~66 K crawler/tier-venue papers (ICLR/NeurIPS/ACL) that OpenAlex mis-fields as Engineering/Medicine or never classifies; the provenance clause keeps them. Both DQ checks are provenance-scoped for the same reason.
2. **AI-concept bucket NOT protected.** Measured: of the 2.48 M delete set only 38 K are `injection_path=concept`, and a 20-sample review showed those are ML-applied domain papers (ESG, green-consumption, acoustofluidics) — not AI research. Protecting them would keep the wrong papers, so they were demoted with the rest.

**Actual numbers:**

| Metric | Before | After |
|---|---:|---:|
| non-stub real papers | 3,743,415 | **1,259,581** |
| stubs | 2,475,577 | 4,959,411 |
| searchable embedded vectors | 715,252* | 426,461 |
| total points | 6,218,992 | 6,218,992 (unchanged — demotion) |

\* baseline captured ~5 % into demotion; true pre-value ≈ 761 K.

**Search latency (bench_search.py, 15 queries, warm, median of 5):**

| | p50 | p90 | mean |
|---|---:|---:|---:|
| before | 433 ms | 474 ms | 438 ms |
| after | 200–207 ms | 221–239 ms | 203–216 ms |

**~2× faster** — larger than the 10-30 % predicted, because the demoted vectors left the HNSW graph entirely (they were valid non-stub search candidates before, so the graph nearly halved: 715 K → 426 K).

**Verification:** both Wave 4c DQ checks green (nontarget 0.0, no-topic 0.0); MCP `search` on 3 canonical queries returns clean EMNLP/ACL/arXiv NLP results with no cross-domain hits; 28 gate+DQ tests pass.

**Recovery map:** `snapshots/2026-07-06-cs-cleanup/delete-ids.jsonl` (2,483,834 rows, gitignored) + the points themselves survive as stubs (re-promote to reverse). Demoted points carry `demoted_from_real=true`, `demoted_reason="wave4c-noncs"` (bool-indexed).

**Remaining:** Phase 4 (chronological labeling of the now-~1 M keep-set backlog) — see §9.

---

## 9. Phase 4 / 4b execution record — 2026-07-13..17

**Phase 4 (labeling), scope reduced to 2020+ by decision.** After measuring the backlog per year bucket (2020-24 = 103 K, 2015-19 = 131 K, 2010-14 = 113 K, pre-2010 ≈ 150-250 K eligible), the user chose to label **only 2020+** — recent papers are the search-relevant ones, and it made node-2 acceleration unnecessary. Labeled 2025-26 (2,109) + 2020-24 (103,297) on node-1 vLLM (`ibm-granite/granite-4.1-8b`) at ~6 K/hr. Committed enablers:
- `label-abstracts --year-min/--year-max` (`798eb66`) — the `abstract_structure` IsEmpty filter is unindexed and full-scans 6.2 M points (now 4.96 M stubs) → 60 s timeout; a `year` range (indexed) bounds it. 2025-26 counted in 3.5 s.
- **stub exclusion in the labeling filter** (`2aa336f`) — it was counting ~8 K enriched stubs with abstracts (2025-26 showed 10,311 "eligible" of which only 2,109 were real papers). `is_stub` added to `must_not` (indexed, also faster).

Node-2 high-util acceleration was attempted (idle 2nd GB10, 93 G free) but abandoned: a mis-submitted util-0.8 job stuck the node-2 sparkq queue and the node-2 daemon runs as `nvidia` (uncancellable from node-1). Node-1 at 6 K/hr was enough at 2020+ scope.

**Phase 4b (re-embed), the step that makes labeling reach search.** Labeling writes `abstract_structure`, but the section vectors (`section-task/method/…`) are generated by the *embedder* from that structure. The ~113 K labeled 2020+ papers already had a stale `structured-abstract` vector, so `embed-papers`' `skip_embedded` (keys on `structured-abstract`) skipped them → they never got `section-*` vectors → the multi-vector search fusion collapsed to abstract+BM25 only. Fixed with a targeted re-embed (`scripts/analytics/reembed_labeled_sections.py`, `57a6969`): forward-paginate `abstract_structure_source=vllm` + `year>=2020` + `must_not HasVector(section-method)` and regenerate all 9 dense vectors via the real embedder. 113,033 papers, ~17 h (Ollama `NUM_PARALLEL=1` serialises). `indexed_vectors` 2.3 M → **3.19 M**. (Residual ~15 K "missing section-method" are legit — their labels have no method-role sentences.)

**Search verified:** hybrid, section-level — "method for contrastive learning of sentence embeddings" → EASE / miCSE / PCL (exact topic).

**Disk/RED:** the re-embed's in-place write churn drove Qdrant RED again while disk was actually healthy (290 G free) — a **stale frozen optimizer error** (`needed 232 GiB / available 225 GiB`, identical for minutes, unmoved by config PATCH). `docker restart qdrant` re-evaluated against live free space → grey → green in ~30 s, size stable 229 G. See [`../refactoring`]… actually the incident + fix live in memory `qdrant-disk-red-incident`; the durable fix remains a dedicated disk with headroom (§ discussed with the user 2026-07-14).

**Still deferred:** pre-2020 labeling (skipped by choice).

**Closed 2026-07-17:** non-article `type` filter inside the keep-set (A1(a) — demoted 44,287 non-paper types, durable P2/P3 `is_keep_type` gate); Ollama-partial re-label (Wave 4b Issue B — verified unnecessary: same granite-4.1-8b model, no truncation; the real gap was `section-*` vectors, closed by a 2010+ re-embed).
