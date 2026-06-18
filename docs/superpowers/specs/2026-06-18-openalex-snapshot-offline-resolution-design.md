# OpenAlex Snapshot — Offline Resolution & Enrichment — Design

**Date:** 2026-06-18
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude Code

## 1. Motivation

The corpus enrichment pipeline's worst throughput bottleneck is the OpenAlex **title-search** endpoint (`/works?search=`), used by the title-lookup stage to enrich papers that have no DOI. The 2026-06-17 full-enrichment run measured **29,769 `429 Too Many Requests`** and **22,368 `Rate limited, waiting 60s`** events on that endpoint before it had to be abandoned. The throttle is **per-IP / effectively global, not per-key** — rotating 6–8 API keys did not help. By contrast, the OpenAlex **by-DOI** endpoint (`/works/{doi}`) was never throttled (0 × 429) in the same run.

OpenAlex publishes a **complete data snapshot** (gzip JSON Lines, ~330 GB compressed, refreshed quarterly, CC0). This design uses that snapshot to enrich the corpus **offline in a single streaming pass**, eliminating the rate-limited search dependency entirely for the backlog. The live by-DOI API remains for daily-fresh papers (which won't be in a quarterly snapshot anyway).

## 2. Scope

**In scope:** all OpenAlex-sourced enrichment served offline from the snapshot — title→work resolution (the bottleneck), DOI→work, abstracts, `referenced_works`, and any other missing metadata — for the existing corpus backlog.

**Out of scope (YAGNI):**
- OpenAlex entities other than **`works`** (no authors/institutions/sources/funders snapshots).
- A persistent local works index (we use a one-pass streaming join, not a queryable mirror).
- Fuzzy title matching (exact normalized title + a corroboration gate only).
- Daily-fresh papers — they stay on the live by-DOI API; the snapshot is the **quarterly backlog** tool.
- The openreview.net PDF-download throttle (stages 3.5/3.8) — unrelated; not solved by OpenAlex.

## 3. Architecture

A quarterly batch with three parts. Implemented as a shared stage function (`enrich_from_snapshot_stage`) callable by a CLI command now and a Dagster asset later — consistent with the Phase 1–2 orchestration pattern.

### 3.1 Snapshot acquisition
- `aws s3 sync --no-sign-request` the OpenAlex **`works`** entity (gzip JSONL, partitioned `.gz` files) to **`/mnt/nfs/ssd2/openalex_snapshot/`** (NFS SSD2 has 1.7 TB free, shared across both Spark nodes). Resumable by re-running the sync.
- Wrapper script `scripts/snapshot/fetch_openalex_snapshot.sh` (downloads works only; logs size/file count).
- **Resolve at plan time:** exact S3 bucket/prefix and the works directory layout, confirmed from `https://developers.openalex.org/download/download-to-machine` (and whether `aws` CLI is installed).

### 3.2 In-memory corpus key index
- Load only papers that **need** enrichment (missing `abstract` OR missing `referenced_works`, OR no-DOI needing resolution) into two maps:
  - `doi → point_id` (DOI matches)
  - `title_norm → list[(point_id, year, first_author_surname)]` (title matches; a list because normalized titles collide)
- ~170 K candidate papers ≈ tens of MB — fits in memory.
- **Reuse the existing resolver title-normalization function** so the snapshot's `title_norm` keys are computed identically to the corpus's.

### 3.3 Streaming join
- New module `src/core/snapshot/` + CLI command `enrich-from-openalex-snapshot`.
- Stream each works `.gz` file line-by-line (JSONL). For each work:
  1. Compute its `doi` and `title_norm`.
  2. **DOI hit** in `doi → point_id` → trusted match.
  3. Else **title hit** in `title_norm → [...]` → accept only if a candidate passes the **corroboration gate** (publication year within ±1 **or** first-author surname overlap).
  4. On match, extract enrichment fields — `abstract` via the existing `_reconstruct_abstract(abstract_inverted_index)`, `referenced_works`, and any missing metadata — and **fill-only-missing** batch-write to Qdrant with a provenance tag.
- **Provenance:** tag snapshot-sourced enrichment (e.g. `enrichment_source: "openalex_snapshot"` payload field) so it's auditable and distinguishable from API-sourced data.
- **Checkpoint:** per-processed-snapshot-file, via the existing `CheckpointMixin`, so the pass is resumable.
- **Dry-run mode:** count prospective matches (DOI / corroborated-title / rejected-title) without writing.

## 4. Match safety (data-quality)

- **DOI match = trusted** (exact identifier).
- **Title match = gated:** exact normalized-title hit **plus** a corroborating signal (year ±1 or first-author surname overlap). Uncorroborated title hits are rejected and counted (visible in dry-run/metrics).
- **Fill-only-missing:** never overwrite an existing non-empty field → idempotent and safe to re-run; a later/better source is never clobbered.
- These three together bound the false-positive risk of the non-unique normalized title.

## 5. Integration & reuse

Reuses existing building blocks (no reinvention):
- `_reconstruct_abstract(abstract_inverted_index)` (`src/core/crawler/openalex.py`).
- Resolver title-normalization (`src/core/resolution/`).
- `CheckpointMixin` (`src/core/checkpoint_mixin.py`).
- Qdrant batch `set_payload` (existing writer path).
- The `referenced_works → resolve-refs` flow: snapshot-sourced refs are OpenAlex IDs and feed the **same** downstream resolution as API-sourced refs (no new ref path).

## 6. Error handling

- Corrupt/unparseable JSONL lines → skip + count (don't abort the pass).
- `aws s3 sync` interruption → resumable by re-running.
- Per-file checkpoint → the streaming join resumes from the last completed file.
- Disk guard: check free space on `/mnt/nfs/ssd2` before sync; the run logs size.

## 7. Testing

- **Unit** (fixture JSONL of a handful of works + a small in-memory corpus map):
  - DOI match → enriches the right point.
  - Title match WITH corroboration → accepted.
  - Title match WITHOUT corroboration → rejected (no write).
  - Fill-only-missing → existing field preserved, missing field filled.
  - Abstract reconstruction from `abstract_inverted_index`.
- **Smoke:** run over a single real `.gz` file, dry-run, against the live corpus — confirm plausible match counts, no writes.

## 8. Freshness & cadence

- Re-run the streaming join after each quarterly snapshot refresh (re-`sync`, re-stream; checkpoints reset for the new snapshot).
- Daily/weekly incremental collection keeps using the live by-DOI API for fresh papers (unaffected).

## 9. Open items (resolve in the implementation plan)
- Exact OpenAlex S3 bucket/prefix + works file layout (from the download-to-machine docs); confirm `aws` CLI availability.
- Provenance field name/shape (`enrichment_source` scalar vs a list) and whether to also stamp a snapshot date.
- Whether to include stub papers in the candidate index (stubs are cited-but-unstored works; the snapshot could fill many — likely yes, but confirm scale/perf at plan time).
- First-author surname extraction from snapshot `authorships` vs our payload for the corroboration check.
