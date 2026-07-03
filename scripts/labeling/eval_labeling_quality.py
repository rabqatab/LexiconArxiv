"""Labeling quality gate: Ollama baseline vs vLLM candidate agreement eval.

Gates the vLLM labeling migration (see ``docs/design/vllm-labeling-migration.md``
§Quality gate). Before we let vLLM overwrite ``abstract_structure`` on the
~3M unlabeled papers in the corpus, we need to prove that the vLLM backend
(candidate) agrees with the Ollama backend (production baseline) on the
same abstracts. If it doesn't, we don't ship — we fall back to Qwen3 on
vLLM or accept the multi-month Ollama-only fallback.

Methodology
-----------
1. **Sample selection.** Draw ``--limit`` (default 60) papers uniformly at
   random from Qdrant, filtered to real (non-stub) papers that already
   have a non-empty ``abstract`` AND a non-empty ``abstract_structure``.
   Requiring existing ``abstract_structure`` means these are papers where
   labeling has previously succeeded on the production Ollama pipeline —
   so a "labeling failed" outcome is genuinely a backend regression, not
   an unlabelable input. Sampling is seeded (``--seed``, default 42) for
   reproducibility.

2. **Dual labeling.** For each paper we run the abstract through:
     - Baseline: ``AbstractLabeler(llm_backend="ollama",
       ollama_model="granite4.1:8b")``.
     - Candidate: ``AbstractLabeler(llm_backend="vllm",
       vllm_model="ibm-granite/granite-4.1-8b")``.
   Both go through the same ``label_abstract`` code path — pysbd splits
   the abstract, the LLM classifies sentences by index, and we recover an
   ``AbstractStructure`` dict keyed by the 7 rhetorical roles.

3. **Agreement metric.** We compare at the (sentence, role) tuple level.
   Because labels are multi-label — a single sentence can be tagged with
   multiple roles — we invert each ``AbstractStructure`` into a
   ``sentence -> set[roles]`` map, then compute Jaccard similarity per
   sentence over the two role sets. Overall agreement is the mean Jaccard
   across all sentences that appear in either output. Per-role agreement
   is computed as micro-F1 over the sentence-role tuples restricted to
   that role.

4. **Schema validity.** A backend that returned ``None`` (LLM/HTTP
   failure, JSON parse failure, or the "no sentences" edge case) is
   counted as schema-invalid. Schema-invalid samples contribute 0.0
   Jaccard to the overall mean (a total mismatch) but are also tracked
   separately in ``schema_valid_count`` for both backends.

5. **Pass condition.**
     - ``overall_agreement >= 0.85`` AND
     - ``schema_valid_count >= 55 / 60`` (>= 91.7%) for BOTH backends.
   These thresholds mirror the 2026-06-19 60-paper eval that originally
   selected granite4.1:8b (see
   ``docs/reference/labeling-llm-comparison.md``).

Output
------
- **stdout**: single JSON document with ``overall_agreement``,
  ``per_role_agreement``, ``schema_valid_count`` (dict per backend),
  ``failure_samples`` (up to 5), ``pass_condition_met``, plus counts.
- **stderr**: human-friendly progress + summary.
- **exit code**: 0 on pass, 1 on fail (including graceful failures like
  "vLLM server not running").

If the vLLM server is down or otherwise unreachable, the script emits a
JSON error object with ``error`` set, ``pass_condition_met=false``, and
exits 1 — never a raw traceback. That way the gate script is safe to
call from CI / sparkq without babysitting.

Usage
-----
    uv run python scripts/labeling/eval_labeling_quality.py
    uv run python scripts/labeling/eval_labeling_quality.py --limit 10 --seed 7
    uv run python scripts/labeling/eval_labeling_quality.py --limit 2 | jq
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import traceback
from pathlib import Path

# Allow running as a standalone script: `uv run python scripts/labeling/...`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.http import models as q  # noqa: E402

from src.core.labeling.labeler import AbstractLabeler  # noqa: E402
from src.core.labeling.llm_base import ROLES  # noqa: E402
from src.core.storage import QdrantStorage  # noqa: E402


# Quality gate thresholds (from docs/design/vllm-labeling-migration.md §Quality gate).
PASS_AGREEMENT = 0.85
PASS_SCHEMA_VALID_MIN = 55
PASS_SAMPLE_SIZE = 60


def _log(msg: str) -> None:
    """Human-friendly progress line to stderr (stdout is reserved for JSON)."""
    print(msg, file=sys.stderr, flush=True)


def _select_eval_papers(storage: QdrantStorage, n: int, seed: int) -> list[dict]:
    """Sample ``n`` real papers that have both ``abstract`` and ``abstract_structure``.

    Filtering strategy: we push the cheap indexed filter (``is_stub !=
    true``) to Qdrant and evaluate the two ``must_not(empty)`` predicates
    client-side. During heavy bootstrap load the fully-server-side
    version (four ``must_not`` conditions on non-indexed payload fields)
    times out at 60s. Client-side evaluation is fine here because we
    only need to inspect an oversample of a few thousand points, not
    scan the full 3M corpus.
    """
    rng = random.Random(seed)

    # Fast filter: only exclude stubs server-side. Everything else is
    # checked in Python from the fetched payload.
    scroll_filter = q.Filter(
        must_not=[
            q.FieldCondition(key="is_stub", match=q.MatchValue(value=True)),
        ],
    )

    oversample_target = max(n * 20, n + 200)
    oversample_target = min(oversample_target, 20_000)

    collected: list[dict] = []
    offset = None
    scanned = 0
    while len(collected) < oversample_target:
        points, offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=scroll_filter,
            limit=256,
            offset=offset,
            with_payload=["title", "abstract", "abstract_structure"],
            with_vectors=False,
        )
        if not points:
            break
        for p in points:
            scanned += 1
            payload = p.payload or {}
            title = payload.get("title") or ""
            abstract = payload.get("abstract") or ""
            existing = payload.get("abstract_structure") or {}
            # Client-side equivalent of the four dropped must_not
            # conditions: reject anything without a non-empty abstract or
            # without a populated abstract_structure.
            if not abstract or not existing:
                continue
            # Guard against payloads where abstract_structure is an empty
            # dict-of-empty-lists (a "labeled but no roles assigned"
            # artifact from the older Ollama path).
            if isinstance(existing, dict) and not any(
                existing.get(r) for r in ROLES
            ):
                continue
            collected.append(
                {
                    "point_id": str(p.id),
                    "title": title,
                    "abstract": abstract,
                }
            )
        if offset is None:
            break
        # Bail out if the corpus has very few labeled papers — no point
        # scanning the whole thing.
        if scanned >= 50_000:
            break

    rng.shuffle(collected)
    return collected[:n]


def _structure_to_sentence_role_map(
    structure: dict | None,
) -> dict[str, set[str]]:
    """Invert an ``AbstractStructure`` dict to ``sentence -> {roles}``.

    A sentence appearing in multiple role lists ends up with all its
    roles collected. Empty/None input yields an empty map — the caller
    treats that as a total mismatch when computing Jaccard.
    """
    out: dict[str, set[str]] = {}
    if not structure:
        return out
    for role in ROLES:
        for sentence in structure.get(role, []) or []:
            key = sentence.strip()
            if not key:
                continue
            out.setdefault(key, set()).add(role)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _compare_one(
    baseline_structure: dict | None,
    candidate_structure: dict | None,
) -> tuple[float, dict[str, dict[str, int]]]:
    """Compare two labeling outputs.

    Returns:
        (mean_sentence_jaccard, per_role_stats) where per_role_stats maps
        role -> {"tp": int, "fp": int, "fn": int} counted over sentence
        tuples. Sentences present in one output but not the other
        contribute the empty set on the missing side.
    """
    base_map = _structure_to_sentence_role_map(baseline_structure)
    cand_map = _structure_to_sentence_role_map(candidate_structure)

    all_sentences = set(base_map) | set(cand_map)

    if not all_sentences:
        # Both outputs failed OR both are empty. Treat as full mismatch
        # only when one side is empty and the other isn't; if both are
        # empty (both failed) we still want 0.0 to penalize agreement
        # rather than paper over the failure.
        agreement = 0.0
    else:
        agreements = [
            _jaccard(base_map.get(s, set()), cand_map.get(s, set()))
            for s in all_sentences
        ]
        agreement = sum(agreements) / len(agreements)

    per_role: dict[str, dict[str, int]] = {
        role: {"tp": 0, "fp": 0, "fn": 0} for role in ROLES
    }
    for sentence in all_sentences:
        b_roles = base_map.get(sentence, set())
        c_roles = cand_map.get(sentence, set())
        for role in ROLES:
            in_b = role in b_roles
            in_c = role in c_roles
            if in_b and in_c:
                per_role[role]["tp"] += 1
            elif in_c and not in_b:
                per_role[role]["fp"] += 1
            elif in_b and not in_c:
                per_role[role]["fn"] += 1

    return agreement, per_role


def _micro_f1(counts: dict[str, int]) -> float:
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    if tp == 0 and fp == 0 and fn == 0:
        # No positives on either side -> perfect (vacuous) agreement.
        return 1.0
    denom = 2 * tp + fp + fn
    if denom == 0:
        return 1.0
    return (2 * tp) / denom


async def _label_paper(
    labeler: AbstractLabeler, title: str, abstract: str
) -> dict | None:
    """Run one paper through a labeler, swallowing exceptions as None."""
    try:
        structure, _source = await labeler.label_abstract(title, abstract)
        return structure
    except Exception as e:
        logging.getLogger(__name__).warning("labeling raised: %s", e)
        return None


async def _run(args: argparse.Namespace) -> dict:
    storage = QdrantStorage()

    _log(f"[eval] sampling {args.limit} papers (seed={args.seed}) ...")
    papers = _select_eval_papers(storage, args.limit, args.seed)
    if not papers:
        return {
            "error": "no eligible papers found in Qdrant "
                     "(need non-stub with abstract AND abstract_structure)",
            "pass_condition_met": False,
        }
    if len(papers) < args.limit:
        _log(
            f"[eval] WARNING: only {len(papers)} eligible papers available "
            f"(requested {args.limit})"
        )

    baseline = AbstractLabeler(
        llm_backend="ollama", ollama_model="granite4.1:8b"
    )
    candidate = AbstractLabeler(
        llm_backend="vllm", vllm_model="ibm-granite/granite-4.1-8b"
    )

    per_paper_results: list[dict] = []
    role_totals: dict[str, dict[str, int]] = {
        role: {"tp": 0, "fp": 0, "fn": 0} for role in ROLES
    }
    schema_valid = {"baseline": 0, "candidate": 0}

    try:
        for idx, paper in enumerate(papers, 1):
            _log(
                f"[eval] {idx}/{len(papers)}  {paper['point_id']}  "
                f"{paper['title'][:60]!r}"
            )
            baseline_structure = await _label_paper(
                baseline, paper["title"], paper["abstract"]
            )
            candidate_structure = await _label_paper(
                candidate, paper["title"], paper["abstract"]
            )

            if baseline_structure is not None:
                schema_valid["baseline"] += 1
            if candidate_structure is not None:
                schema_valid["candidate"] += 1

            agreement, per_role = _compare_one(
                baseline_structure, candidate_structure
            )
            for role in ROLES:
                for k in ("tp", "fp", "fn"):
                    role_totals[role][k] += per_role[role][k]

            per_paper_results.append(
                {
                    "point_id": paper["point_id"],
                    "title": paper["title"][:120],
                    "agreement": agreement,
                    "baseline_ok": baseline_structure is not None,
                    "candidate_ok": candidate_structure is not None,
                    "baseline_structure": baseline_structure,
                    "candidate_structure": candidate_structure,
                }
            )
    finally:
        await baseline.close()
        await candidate.close()

    n = len(per_paper_results)
    overall_agreement = (
        sum(r["agreement"] for r in per_paper_results) / n if n else 0.0
    )
    per_role_agreement = {
        role: _micro_f1(role_totals[role]) for role in ROLES
    }

    # Sort worst-first, keep up to 5 mismatches for spot-checking.
    failure_samples = sorted(
        per_paper_results, key=lambda r: r["agreement"]
    )[:5]
    # Trim the failure samples to keep the JSON reasonable.
    failure_samples = [
        {
            "point_id": r["point_id"],
            "title": r["title"],
            "agreement": r["agreement"],
            "baseline_ok": r["baseline_ok"],
            "candidate_ok": r["candidate_ok"],
            "baseline_structure": r["baseline_structure"],
            "candidate_structure": r["candidate_structure"],
        }
        for r in failure_samples
    ]

    pass_condition_met = (
        overall_agreement >= PASS_AGREEMENT
        and schema_valid["baseline"] >= PASS_SCHEMA_VALID_MIN
        and schema_valid["candidate"] >= PASS_SCHEMA_VALID_MIN
    )

    return {
        "sample_size": n,
        "requested_limit": args.limit,
        "seed": args.seed,
        "overall_agreement": overall_agreement,
        "per_role_agreement": per_role_agreement,
        "schema_valid_count": schema_valid,
        "pass_thresholds": {
            "overall_agreement": PASS_AGREEMENT,
            "schema_valid_min": PASS_SCHEMA_VALID_MIN,
            "reference_sample_size": PASS_SAMPLE_SIZE,
        },
        "failure_samples": failure_samples,
        "pass_condition_met": pass_condition_met,
    }


def _print_summary(report: dict) -> None:
    _log("")
    _log("=" * 60)
    _log("LABELING QUALITY GATE SUMMARY")
    _log("=" * 60)
    if "error" in report:
        _log(f"  error: {report['error']}")
        _log(f"  pass:  {report['pass_condition_met']}")
        return
    _log(f"  samples:              {report['sample_size']}")
    _log(f"  overall agreement:    {report['overall_agreement']:.4f}  "
         f"(threshold {report['pass_thresholds']['overall_agreement']})")
    sv = report["schema_valid_count"]
    _log(f"  schema-valid baseline: {sv['baseline']}/{report['sample_size']}")
    _log(f"  schema-valid candidate: {sv['candidate']}/{report['sample_size']}")
    _log("  per-role agreement:")
    for role, score in report["per_role_agreement"].items():
        _log(f"    {role:>14}: {score:.4f}")
    _log(f"  PASS: {report['pass_condition_met']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ollama vs vLLM labeling agreement quality gate."
    )
    parser.add_argument(
        "--limit", type=int, default=PASS_SAMPLE_SIZE,
        help=f"Number of papers to sample (default: {PASS_SAMPLE_SIZE}).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible sampling (default: 42).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        report = asyncio.run(_run(args))
    except Exception as e:
        # Graceful failure: emit JSON, not a traceback, and exit 1.
        report = {
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "pass_condition_met": False,
        }

    _print_summary(report)
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0 if report.get("pass_condition_met") else 1


if __name__ == "__main__":
    sys.exit(main())
