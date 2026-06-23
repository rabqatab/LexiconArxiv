# Corpus Gap Discovery (P3)

P3 of the snapshot utilization system. Find OpenAlex works that are NOT in our
corpus but should be, and inject them as new real papers.

## Hybrid relevance — two paths

`src/core/snapshot/gap_filter.py:classify`:

| Path | Condition | Rationale |
|---|---|---|
| **ANCHOR_INJECT** | The work's OpenAlex ID appears in our corpus's `referenced_works` of ≥ `anchor_min_citers` (default 2) papers | Papers we already cite are by definition relevant to our research domain |
| **CONCEPT_INJECT** | The work has at least one `concepts[].id` in `AI_CONCEPT_IDS` AND `publication_year ≥ concept_min_year` (default 2018) AND `cited_by_count` meets the age-scaled threshold (default ≥50 for ≤5-year-old papers, ≥200 otherwise) | Cast a wider net: high-impact AI papers in venues we don't crawl |
| **REJECT** | Neither path matches | |

When both paths qualify, ANCHOR wins (recorded `injection_path = "anchor"`).

## AI concept taxonomy

`AI_CONCEPT_IDS` is a 17-element set of OpenAlex C-namespace IDs (Artificial
intelligence, Machine learning, Deep learning, NLP, Computer vision,
Reinforcement learning, Neural network, Generative model, Transformer,
Knowledge graph, Information retrieval, Recommender system, Robotics, Speech
recognition, Federated learning, Multi-agent system, Foundation model).

To update: fetch the latest tree under `C154945302` (Artificial intelligence)
from `https://api.openalex.org/concepts?filter=ancestors.id:C154945302` and
expand `AI_CONCEPT_IDS` with any new high-level IDs.

## Thresholds — how to tune

Defaults (in `Thresholds`):
- `anchor_min_citers = 2`
- `concept_min_recent = 50` (papers ≤ 5 years old)
- `concept_min_old = 200`
- `concept_min_year = 2018`

These are surfaced as CLI options. Bootstrap procedure:

```bash
# Day 6 dry-run with defaults
uv run python -m src.cli.core_collect discover-corpus-gaps --dry-run --limit-files 30
```

The dry-run prints `anchor_inject`, `concept_inject`, `rejected`,
`year_distribution`, and `top_concepts` — review:

- If `concept_inject / scanned` is too high (e.g. > 0.5%), raise
  `--concept-min-recent` to 100 and `--concept-min-old` to 400 and re-dry-run.
- If `anchor_inject` looks low, lower `--anchor-min-citers 1` (every paper we
  cite, even once).

Then run with `--max-injections 5000` for a first real pass to validate, then
without the cap for the full pass.

## Safety: the `--max-injections` cap

Always pass `--max-injections N` on the first real run. The phase
**short-circuits** when the cap is reached and records `extra["capped"]=True` in
the summary. Re-running without the cap will continue from the checkpoint of
the next unprocessed `.gz`.

## In-pass dedup

Each `process_one` checks against `dedup_idx` (built from the corpus at the
start) AND updates it after every successful injection. So a same-pass second
occurrence of the same DOI/openalex_id is skipped as `skipped_dup`.

## Provenance

Every injected point receives:

```
{
  "is_stub": false,
  "injected_from_snapshot": true,
  "injection_path": "anchor" | "concept",
  "injected_at": "<UTC ISO>",
  "snapshot_filled_at": "<UTC date>"
}
```

This makes it trivial to roll back a bad run by filtering on
`injected_from_snapshot=true AND injected_at >= <date>`.

## Cleanup procedure (bad run)

See `docs/runbooks/snapshot-rollback.md` for the script to remove a recent
batch of injections.
