# OpenAlex Snapshot Utilization — Design

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plans
**Author:** brainstormed with Claude Code

## 1. Motivation

We have a local OpenAlex `works` snapshot (≈594 GB gzip JSONL at
`/mnt/nfs/ssd2/openalex_snapshot/data/works/updated_date=*/part_*.gz`) of which
the current `enrich-from-openalex-snapshot` command exploits only **2 fields**
(`abstract`, `referenced_works`) on non-stub papers. Each work has **49 fields**
including `cited_by_count`, `fwci`, `citation_normalized_percentile`,
`counts_by_year`, `concepts`, `topics`, `best_oa_location.pdf_url`,
`authorships[].orcid` — and the snapshot is, in effect, a local mirror of the
entire OpenAlex graph. Three backlog items have been blocked by OpenAlex
title-search 429 throttling, all solvable with this snapshot:

- "Resolve TITLE: stubs" (`docs/plans/TODO.md:14`)
- "Enrich high-value stubs — 23,960 stubs cited by 20+ core papers" (`TODO.md:13`)
- "Corpus gap dashboard" + "Stub → core promotion" (`TODO.md:15-16`, no code today)

This design unlocks all of them, plus a bonus pass that fills the unused 47
fields on existing real papers.

## 2. Scope

The system reshapes the corpus through four **independent, phased passes** over
the snapshot, each runnable on its own, each idempotent (fill-only-missing),
each with its own checkpoint. A live-mode wrapper applies the same four pass
modules to OpenAlex API delta one work at a time, so the bootstrap and the
daily incremental use identical logic.

User-confirmed scope decisions (from brainstorming):
- **Maximum-ambition transformation:** stub→real promotion (new code path),
  gap papers injected as new real papers (skipping stub stage), corpus-internal
  cited_by edges added. Not just in-place field-fill.
- **Hybrid relevance for gap discovery:** citation-anchor (papers our corpus
  cites) ∪ AI-concept high-impact recent.
- **Cited-by extension:** metric fill + corpus-internal edges only (no global
  reverse-citation index to prevent payload explosion).
- **Embed immediately:** every promoted or injected paper with an abstract is
  queued for embedding right away.
- **Balanced gap-injection threshold:** anchor path low (≥2 internal citers),
  concept path strict (cited_by_count threshold scaled by paper age + recency
  bound).
- **Continuous sync:** bootstrap once, snapshot re-pass quarterly, live API
  delta daily — same module called from all three.

Out of scope (deliberate, YAGNI):
- Search-ranking changes that use the new fields (separate brainstorm).
- A global "who cites me from outside the corpus" index (rejected for blast
  radius; see §3 P4).
- Replacing the existing in-corpus citation graph builder/analyzer (the new
  `external_cited_by` field is **additive**, not a replacement).

## 3. Architecture — four phased passes

```
P1 enrich-corpus-fields    (bonus)  : real papers in corpus → fill missing fields
                                       (cited_by_count, fwci, percentile, topics,
                                        concepts, OA pdf_url, orcid_map, ...)

P2 resolve-stubs-from-snapshot (A)  : every stub → match in snapshot → promote
                                       to real (is_stub=False, preserve cited_by)
                                       or enrich-in-place + queue embedding

P3 discover-corpus-gaps     (B)     : every snapshot work not in corpus →
                                       (anchor or concept relevance) → inject as
                                       new real paper + queue embedding

P4 extend-cited-by-from-snapshot (C): every snapshot work → if its references
                                       hit corpus → add citer to that paper's
                                       new external_cited_by field
```

**Dependency / gate order:**
- P1 is independent (no corpus mutation).
- P2 must precede P3 conceptually (stub→real changes the "in corpus" set P3
  reads), but the runtimes can be sequenced freely.
- P3 must precede P4 (P4 should see all newly-injected points).
- **Gate between P2/P3 and P4:** the embedding queue from P2 and P3 must drain
  before P4. Otherwise newly-injected points have no vectors when P4 attaches
  their citers, which is fine for the payload write but inconsistent with the
  user expectation that all gap papers are searchable before reverse-edges
  appear in the UI.

**Live-mode mapping (daily API delta):** each module exports
`process_one(work: dict) -> Result`. The live worker fetches yesterday's delta
from `/works?from_updated_date=YYYY-MM-DD` and calls
`p1.process_one(w) → p2.process_one(w) → p3.process_one(w) → p4.process_one(w)`
for each work. Same logic, different data source.

## 4. Module structure

```
src/core/snapshot/
├── runner.py                  [EXISTING — kept as alias for one release]
├── matcher.py                 [EXTEND]  + match_work_for_stubs, stub indexers
├── extractor.py               [NEW]     field-by-field extraction from a work dict
├── work_source.py             [NEW]     iter_works_for_phase(source="snapshot"|"live")
├── phase1_corpus_fields.py    [NEW]     P1 module, exports run() + process_one()
├── phase2_stub_resolution.py  [NEW]     P2 module, same pattern
├── phase3_gap_discovery.py    [NEW]     P3 module, same pattern
├── phase4_cited_by.py         [NEW]     P4 module, same pattern
├── promotion.py               [NEW]     promote_one() transaction (see §5)
├── gap_filter.py              [NEW]     P3 relevance: ANCHOR_INJECT|CONCEPT_INJECT|REJECT
├── embedding_queue.py         [NEW]     append/cancel/drain, disk-persisted
├── checkpoint.py              [NEW]     per-phase file-level done set + failed/quarantine
└── stats.py                   [NEW]     phase summary dataclasses + log helpers

src/core/storage/
├── stubs.py                   [EXTEND]  iter_stubs_for_resolution(),
│                                        merge_stub_into_real(),
│                                        find_real_by_identifier()
├── writer.py                  [EXTEND]  batch_apply_field_fill(),
│                                        batch_promote_stubs(),
│                                        batch_inject_papers(),
│                                        batch_extend_external_cited_by()
├── reader.py                  [EXTEND]  iter_all_real_papers_minimal(),
│                                        build_referenced_openalex_id_set(),
│                                        build_openalex_id_to_point_id_map(),
│                                        build_identifier_index_for_dedup()
└── base.py                    [EXTEND]  facade delegation only

src/cli/commands/snapshot.py   [EXTEND]  4 new phase commands +
                                          snapshot-status / replay / reset

src/orchestration/assets/snapshot.py [NEW] 4 assets + snapshot_bootstrap_job +
                                            snapshot_live_delta asset (later plan)

tests/core/snapshot/           [NEW]     fixtures + L1/L2 tests per phase
```

Separation of concerns (`who does what`):
| concern | location | why |
|---|---|---|
| parse a work into payload-shaped fields | `extractor.py` | parsing is phase-agnostic |
| read works from snapshot OR live API | `work_source.py` | hides data source from phases |
| match a work to corpus / stubs | `matcher.py` | shared by P2/P3/P4 |
| phase-specific business logic | `phaseN_*.py` | single responsibility |
| stub→real transaction (preserve cited_by, rollback) | `promotion.py` | safety-critical, isolated |
| hybrid relevance decision | `gap_filter.py` | thresholds change often |
| handoff to embedder | `embedding_queue.py` | explicit boundary |
| restart safety | `checkpoint.py` | per-phase done-files + quarantine |
| DB writes | `storage/writer.py` extensions | phases stay storage-agnostic |
| trigger | `cli/commands/snapshot.py`, Dagster asset | follows existing patterns |

## 5. Data flow per phase

Each phase follows the same skeleton:
**(prepare indices) → (stream works) → (batch flush) → (mark checkpoint) → (summary)**.
Provenance is recorded via `snapshot_filled_at` / `promoted_at` / `injected_at` /
`live_filled_at` payload keys.

### P1 — `enrich-corpus-fields`
1. Build `(point_id, doi_norm, openalex_id, title_norm)` index from
   `iter_all_real_papers_minimal()` (≈50 MB).
2. For each snapshot work: `match_work` → if a corpus point, call
   `extractor.extract_p1_fields(work, existing_payload)` (fill-only-missing) →
   batch `set_payload`.
3. Mark each `.gz` done in `checkpoint.mark_done("p1", filename)`.
4. Summary: `{scanned, matched, fields_filled_by_name, files_done}`.

Fields P1 fills (when missing): `cited_by_count`, `fwci`,
`citation_normalized_percentile`, `counts_by_year`, `concepts`, `topics`,
`primary_topic`, `best_oa_pdf_url` (from `best_oa_location.pdf_url`), `orcid_map`
(from authorships), `sustainable_development_goals`, `funders`, `institutions`,
`mesh`, `language`, `open_access`. The complete mapping lives in
`docs/reference/snapshot-fields.md`.

### P2 — `resolve-stubs-from-snapshot`
1. Build stub index: `(doi_map, arxiv_map, title_map, openalex_map)` from
   `iter_stubs_for_resolution()`. Includes `alternate_identifiers`.
2. For each work: `match_work_for_stubs(work, indexes)`. If hit, run
   `promotion.evaluate(stub, work_fields)`:
   - `PROMOTE` if title AND (abstract OR (year AND ≥1 author))
   - `ENRICH_KEEP_STUB` if only partial metadata gained
   - `SKIP` if nothing new
3. Batch flush via `storage.batch_promote_stubs(...)` or
   `batch_apply_field_fill(...)`. Promoted points with abstracts go to
   `embedding_queue`.
4. Summary: `{stubs_seen, doi/arxiv/title/openalex_matches, promoted, enriched,
   merged, queued_for_embed}`.

### P3 — `discover-corpus-gaps`
Run after P2 so the dedup index reflects all promotions.
1. Build (`existing_identifier_set`, `referenced_anchor_set`,
   `AI_concept_taxonomy`).
2. For each work not in corpus: `gap_filter.classify(work, anchor_set)`:
   - `ANCHOR_INJECT` if `wid in referenced_anchor` AND ≥2 internal citers
   - `CONCEPT_INJECT` if AI concept tag AND `cited_by_count ≥ THRESH_BY_AGE`
     (≤5y: 50; older: 200) AND publication_year ≥ 2018
   - else `REJECT`
3. `batch_inject_papers(pending)` creates new vectorless points; abstracted
   ones go to `embedding_queue`. In-pass dedup set prevents double-creation.
4. Summary: `{anchor_inject, concept_inject, rejected, queued_for_embed,
   year_distribution, top_concepts}`.

### P4 — `extend-cited-by-from-snapshot`
Run after P2+P3 and after `embedding_queue` is drained.
1. Build `oa_id → point_id` map of all corpus real papers.
2. For each work: collect refs that hit the corpus, group by cited point, batch
   append to `external_cited_by` (read-union-write per point, deterministic
   truncation to 300 entries by `(year DESC, cited_by_count DESC)` if over).
3. `external_cited_by` is a **separate field** from the existing `cited_by`
   (which holds internal point IDs from `build_cited_by_index`); the two are
   composed only at search/ranking time.
4. Summary: `{hits, points_updated, edges_added, top_cited_in_corpus}`.

## 6. Promotion transaction (§P2 in depth)

Qdrant has no multi-point ACID transactions, so promotion uses idempotent
steps with explicit verify+rollback:

```
promote_one(storage, stub, work_fields):
  backup = stub.snapshot()
  try:
    # A. dedup guard: if a real paper already exists with this DOI/OA-id/arXiv,
    #    merge stub.cited_by into it and delete the stub instead.
    real_dup = storage.find_real_by_identifier(work_fields)
    if real_dup:
      storage.merge_stub_into_real(stub.point_id, real_dup.point_id)
      return MERGED_INTO_EXISTING

    # B. payload swap (idempotent — same key writes again are no-ops)
    storage.set_payload(stub.point_id, {
      **work_fields,
      "is_stub": False,
      "cited_by": stub.cited_by,                # ← preserved
      "cited_by_count": len(stub.cited_by),
      "cited_by_count_internal": stub.cited_by_count_internal,
      "alternate_identifiers": stub.alternate_identifiers or {},
      "promoted_from_stub": True,
      "promoted_at": utcnow_iso(),
      "snapshot_filled_at": utcnow_iso(),
    })

    # C. verify (asserts: is_stub flipped, cited_by NOT lost)
    after = storage.get_payload(stub.point_id)
    assert after["is_stub"] is False
    assert set(after["cited_by"] or []) >= set(stub.cited_by)

    # D. queue for embedding (only if abstract present)
    if work_fields.get("abstract"):
      embedding_queue.append(stub.point_id, source="promotion")

    return PROMOTED

  except (AssertionError, Exception) as e:
    storage.set_payload(stub.point_id, backup.payload)  # restore
    embedding_queue.cancel(stub.point_id)
    raise PromotionError(stub.point_id, str(e))
```

cited_by preservation is the single most important invariant — tested
explicitly in `tests/core/snapshot/test_promotion.py` and verified post-pass by
a corpus-level query (`promoted_from_stub=True AND cited_by==[]` must be 0).

## 7. Error handling, transactions, checkpoints

Failure taxonomy (full table in §4 of the brainstorming notes, summarized here):
| class | response | counter |
|---|---|---|
| benign noise (JSONDecodeError on a line) | skip, debug log | `skipped_decode` |
| per-work processing error | skip, warn 1/100 | `worker_errors` |
| batch write error | exponential backoff 3× → dump to `failed_batches/` | `failed_batches` |
| transactional invariant violation | per-work rollback, write to `quarantine/<phase>.jsonl` | `quarantined` |
| infra unavailable (Qdrant/Ollama) | flush current batch, exit cleanly | (resume next run) |
| SIGTERM | flush + mark + exit 0 | `clean_exit` |

If `worker_errors / scanned > 1%` warn at finish; if `> 10%` exit code 2 to
force operator attention. Failed batches and quarantine are replayed by
`snapshot-replay-failed --phase <p>`, never auto-replayed.

Checkpoint layout (file-level, atomic enough for our cadence):
```
$DAGSTER_HOME/snapshot_checkpoints/
├── p{1,2,3,4}/
│   ├── done_files.txt                 # one absolute path per processed .gz
│   ├── last_summary.json              # operator dashboard
│   ├── live_high_water_mark.iso       # live-mode last delta timestamp
│   ├── failed_batches/<ts>.jsonl
│   └── quarantine.jsonl
```

P4 read-modify-write race protection: single-worker assumption + in-process
per-point `Lock` dict (LRU 10k entries) serializes the `external_cited_by`
append-and-dedup against live-mode P4 calls.

Memory ceilings (single host, GB10 128 GB unified): P1 ≈ 50 MB, P2 ≈ 150 MB,
P3 ≈ 300 MB, P4 ≈ 50 MB. Comfortable.

## 8. Testing

Three-layer model:
- **L1 unit:** `extractor`, `matcher`, `gap_filter`, `promotion`,
  `embedding_queue`, `checkpoint` — pure functions + mock storage, always run
  in CI.
- **L2 integration:** each `phaseN_*.run()` end-to-end against an in-memory
  storage stub and the `tests/core/snapshot/fixtures/works/tiny.jsonl.gz`
  fixture (~50 hand-curated works covering all matching scenarios). Always run
  in CI.
- **L3 live-smoke:** real Qdrant + one real `~30k`-work `.gz`, gated by
  `@pytest.mark.snapshot_live`. Operator-only.

Fixture layout, mock_storage design, and per-phase invariant assertions are
documented in `tests/core/snapshot/README.md` (created with Plan 1). Regression
tests for the count-bug (`dq exact`) and empty-string-abstract bug already exist
in `tests/core/test_dq.py`.

Pytest markers (added to `pyproject.toml`):
```
markers = [
  "integration: requires running services (Ollama/Qdrant)",
  "snapshot_live: requires real snapshot fixture (large, slow)",
]
```
CI default: `pytest -m "not snapshot_live"`.

## 9. CLI and Dagster

Commands (same dry-run / resume / limit-files semantics across all phases):
```
enrich-corpus-fields              [--dry-run] [--limit-files N] [--batch-size]
resolve-stubs-from-snapshot       [--allow-promotion/--no-allow-promotion]
                                  [--allow-merge/--no-allow-merge]
discover-corpus-gaps              [--anchor-min-citers] [--concept-min-recent]
                                  [--concept-min-old] [--concept-min-year]
                                  [--max-injections]
extend-cited-by-from-snapshot     [--max-citers-per-paper]
snapshot-status                   # checkpoint progress + queue depth + quarantine
snapshot-replay-failed --phase {p1..p4} [--quarantine]
snapshot-reset --phase {p1..p4} --confirm
embed-papers --consume-snapshot-queue   # extension to existing command
```

Dagster (`src/orchestration/assets/snapshot.py`):
- 4 assets, dependencies as in §3.
- `snapshot_bootstrap_job` = all four. **No schedule** — manual launch only.
- `snapshot_live_delta` asset + `daily_snapshot_live_schedule` (cron, default
  `STOPPED`) — deferred to a later plan; this spec only fixes the interface.

## 10. Operations

Bootstrap is a multi-day staged run with operator gates between phases —
documented as `docs/runbooks/snapshot-bootstrap.md`. Outline:
- Day 0: backup Qdrant, check SSD/Ollama, baseline `embed-papers --dry-run`.
- Day 1: P1 `--dry-run --limit-files 50` → review fields_filled_by_name.
- Day 2: P1 full (≈6h, no corpus mutation).
- Day 3: P2 `--dry-run` → P2 full → spot-check promoted points in UI.
- Days 4–5: drain embedding queue (`embed-papers --consume-snapshot-queue`).
- Day 6: P3 `--dry-run` → P3 with `--max-injections 5000` first → tune → full.
- Days 7–9: drain embedding queue again.
- Day 10: P4 (lightest, ~2–3h).
- Day 11+: re-run analytics (similarity / graph / topics).

Rollback paths (`docs/runbooks/snapshot-rollback.md`):
| situation | response |
|---|---|
| wrong promotions (small batch) | `snapshot-reset --phase p2` + identify by `promoted_from_stub=True AND <recent>` + scripted payload restore |
| P3 injection runaway | next pass `--max-injections N`; clean recent injections via `injected_from_snapshot=True AND <recent>` |
| Qdrant corruption | restore backup, re-run snapshot commands (idempotent) |
| embedding queue lost | reconstruct: `(promoted OR injected) AND no vector AND has abstract` |

## 11. Documentation strategy

Three-layer doc model with explicit anti-rot rules:
| layer | purpose | location | update cadence |
|---|---|---|---|
| Spec (this file) | intent + decisions + tradeoffs (frozen) | `docs/superpowers/specs/` | superseded only |
| Plan | task checklist | `docs/superpowers/plans/` | updated during implementation, frozen at end |
| Reference / Pipeline / Runbook | the truth about the running system | `docs/reference/`, `docs/pipelines/`, `docs/runbooks/` | **updated in the same PR as the code** |

Rules to keep docs fresh (enforced in PR review):
1. New phase code → same-PR update to `docs/pipelines/*.md`.
2. CLI option change → same-PR sync of `--help` and `runbooks/snapshot-bootstrap.md`.
3. Disk schema change (quarantine, failed_batches, external_cited_by) → same-PR
   update of `docs/reference/snapshot-fields.md` and regression tests.
4. Reference = "what is this", Runbook = "how do I do this". Don't mix.
5. `MEMORY.md` records *why* decisions were made, not corpus state.

Documents this design will create or update:
- `docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md` (this)
- `docs/superpowers/plans/2026-06-21-snapshot-utilization-plan{1..4}.md`
- `docs/reference/snapshot-fields.md` (new)
- `docs/pipelines/stub-promotion.md` (new)
- `docs/pipelines/corpus-gap-discovery.md` (new)
- `docs/pipelines/citation_graph.md` (update — add external_cited_by)
- `docs/runbooks/snapshot-bootstrap.md` (new)
- `docs/runbooks/snapshot-rollback.md` (new)
- `tests/core/snapshot/README.md` (new)
- Memory: `reference_openalex_snapshot.md` extended, `project_dagster_status.md`
  updated with snapshot job, new `reference_snapshot_pipeline.md`.

## 12. Implementation split

Four plans, mergeable independently after Plan 1:

| Plan | Range | Tasks (est.) | LOC | Gate |
|---|---|---|---|---|
| **Plan 1: Foundation** | `extractor`, `work_source`, `checkpoint`, `embedding_queue`, matcher extension, storage extensions, test infrastructure (fixtures + mock_storage), keep `runner.py` as alias | ~25 | ~700 | unit tests 100% |
| **Plan 2: P1 + P4** | `phase1_corpus_fields`, `phase4_cited_by`, 2 CLI, 2 assets, `docs/reference/snapshot-fields.md`, bootstrap P1/P4 sections | ~15 | ~500 | P1 live run + counters reviewed |
| **Plan 3: P2 (promotion)** | `phase2_stub_resolution`, `promotion`, stub storage extensions, P2 CLI/asset, `docs/pipelines/stub-promotion.md`, runbook P2 section | ~20 | ~600 | P2 live run + invariant query passes |
| **Plan 4: P3 (gap discovery)** | `phase3_gap_discovery`, `gap_filter`, AI taxonomy, P3 CLI/asset, `docs/pipelines/corpus-gap-discovery.md`, runbook P3 section | ~20 | ~600 | P3 dry-run reviewed → staged real run |

Live-mode wrapper (Plan 5) is deferred until all four phases are operationally
stable. This spec defines the `process_one(work)` interface only.

## 13. Risks

| # | risk | mitigation |
|---|---|---|
| R1 | P2 loses `cited_by` (transaction bug) | invariant unit test + post-pass corpus query + Qdrant backup |
| R2 | P3 injection runaway (bad thresholds) | `--max-injections`, `--dry-run`, `--limit-files`, staged bootstrap |
| R3 | embedding queue stalls indefinitely | `snapshot-status` queue depth, new DQ warn-check `embedding_queue_drained` |
| R4 | `external_cited_by` explosion | start at 300 cap, measure distribution post-bootstrap, tune |
| R5 | AI taxonomy too narrow/wide | dry-run before real → tune taxonomy + thresholds once, then run |
| R6 | infra failure mid-bootstrap | file-level checkpoints + idempotency: re-run same command |
| R7 | live + quarterly race on `external_cited_by` | single-worker + per-point Lock; live job STOPPED during quarterly run |
| R8 | OpenAlex schema change | defensive `.get()` + extractor unit tests for missing keys |

## 14. Open questions (to resolve at plan-writing or pre-bootstrap)

1. Exact AI taxonomy OpenAlex concept IDs — Plan 4 fetches from
   `https://api.openalex.org/concepts` at implementation time.
2. Exact `external_cited_by` cap — start 300, measure, tune.
3. embedding queue on-disk format — JSONL default; reconsider SQLite in Plan 1
   if query-ability is needed.
4. Live-mode worker infrastructure (systemd timer vs Dagster sensor) — Plan 5.
5. Whether the new impact fields feed search ranking — separate brainstorm.
6. Confirm `embed-papers` builds BM25 for promoted/injected papers — Plan 3
   task to verify.

## 15. Success criteria

After bootstrap completes, all of the following hold:
1. P1 covers strictly more fields than the old `enrich-from-openalex-snapshot`
   (≥ 5 new fields filled).
2. P2 promotes ≥ 1,000 stubs, all preserving `cited_by`
   (`promoted_from_stub=True AND cited_by==[]` is 0).
3. P3 injects within the balanced window (anchor + concept combined in the
   thousands-to-low-tens-of-thousands), with classification counters visible.
4. P4 has populated `external_cited_by` on a sensible fraction of corpus
   papers (covers newly promoted/injected too).
5. All DQ asset_checks pass (especially blocking #3/#6/#7).
6. Search API surfaces P2-promoted papers, P3-injected papers, and P1-filled
   fields.
7. `snapshot-status` reports `last_summary` + 0 quarantine per phase.
