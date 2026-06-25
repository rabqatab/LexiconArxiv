"""Stub→real promotion: decision + per-stub transaction (verify + rollback)."""
import logging
from datetime import datetime, timezone
from enum import Enum

from src.core.snapshot import embedding_queue

logger = logging.getLogger(__name__)


class Decision(str, Enum):
    PROMOTE = "PROMOTE"
    ENRICH_KEEP_STUB = "ENRICH_KEEP_STUB"
    SKIP = "SKIP"
    MERGED_INTO_EXISTING = "MERGED_INTO_EXISTING"


def _has(d: dict | None, key: str) -> bool:
    if not d:
        return False
    v = d.get(key)
    return v not in (None, "", [], {})


def _gains(stub: dict, fields: dict) -> dict:
    """Return only the fields that would actually add something the stub lacks."""
    out = {}
    for k, v in fields.items():
        if v in (None, "", [], {}):
            continue
        if _has(stub, k):
            continue
        out[k] = v
    return out


def evaluate(
    stub: dict,
    work_fields: dict,
    *,
    min_cited_by_count: int = 0,
) -> Decision:
    """Decide what to do with this match.

    *min_cited_by_count*: if the snapshot work has fewer external citations
    than this, drop the promotion to ENRICH_KEEP_STUB (still fill payload gaps
    but keep is_stub=true). Default 0 = no filter (every match that meets the
    base PROMOTE criteria gets promoted). Operator dials this up to keep the
    corpus biased toward well-cited references — protects against the bootstrap
    promoting millions of low-signal external papers into the search index.
    The stub itself still gets enriched in-place; only the is_stub→false flip
    is gated."""
    gains = _gains(stub, work_fields)
    if not gains:
        return Decision.SKIP

    # After enrichment, would we meet PROMOTE criteria?
    title_after = work_fields.get("title") or stub.get("title")
    abstract_after = work_fields.get("abstract") or stub.get("abstract")
    year_after = work_fields.get("year") or stub.get("year")
    authors_after = work_fields.get("authors") or stub.get("authors") or []

    base_eligible = title_after and (
        abstract_after or (year_after and len(authors_after) >= 1)
    )
    if not base_eligible:
        return Decision.ENRICH_KEEP_STUB

    # Quality gate: external citation floor (use snapshot work value, not stub —
    # stub's cited_by_count_internal is corpus-internal, not OpenAlex global).
    if min_cited_by_count > 0:
        cited_by_count = work_fields.get("cited_by_count") or 0
        if cited_by_count < min_cited_by_count:
            return Decision.ENRICH_KEEP_STUB

    return Decision.PROMOTE


class PromotionError(Exception):
    """Raised when batch_promote_stubs returns status != 'promoted'."""

    def __init__(self, point_id: str, reason: str):
        self.point_id = point_id
        self.reason = reason
        super().__init__(f"{point_id}: {reason}")


def promote_one(
    storage,
    stub: dict,
    work_fields: dict,
    *,
    embedding_queue_root=None,
    allow_merge: bool = True,
) -> Decision:
    """Run one promotion transaction. Raises PromotionError on verify failure.

    If *allow_merge* is False and a real duplicate is found via the dedup guard,
    the function returns MERGED_INTO_EXISTING WITHOUT calling merge_stub_into_real.
    The caller interprets this as "merge was blocked by policy".
    """
    pid = stub["point_id"]

    # A. dedup guard
    real_dup = storage.find_real_by_identifier({
        "doi": work_fields.get("doi") or stub.get("doi"),
        "openalex_id": work_fields.get("openalex_id") or stub.get("openalex_id"),
        "arxiv_id": work_fields.get("arxiv_id") or stub.get("arxiv_id"),
    })
    if real_dup and real_dup != pid:
        if not allow_merge:
            return Decision.MERGED_INTO_EXISTING
        storage.merge_stub_into_real(pid, real_dup)
        return Decision.MERGED_INTO_EXISTING

    # B. batch_promote_stubs (the storage call does set_payload + verify)
    result = storage.batch_promote_stubs([{
        "point_id": pid,
        "work_fields": work_fields,
        "preserved_cited_by": list(stub.get("cited_by") or []),
        "preserved_cited_by_count_internal": stub.get("cited_by_count_internal", 0),
        "preserved_alternate_identifiers": stub.get("alternate_identifiers") or {},
    }])
    if not result:
        raise PromotionError(pid, "batch_promote_stubs returned no result")
    r = result[0]
    if r["status"] != "promoted":
        raise PromotionError(pid, r.get("error") or r["status"])

    # C. queue for embedding if abstract present
    if work_fields.get("abstract"):
        embedding_queue.append(pid, source="promotion", root=embedding_queue_root)

    return Decision.PROMOTE
