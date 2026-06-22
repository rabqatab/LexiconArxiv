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


def evaluate(stub: dict, work_fields: dict) -> Decision:
    """Decide what to do with this match."""
    gains = _gains(stub, work_fields)
    if not gains:
        return Decision.SKIP

    # After enrichment, would we meet PROMOTE criteria?
    title_after = work_fields.get("title") or stub.get("title")
    abstract_after = work_fields.get("abstract") or stub.get("abstract")
    year_after = work_fields.get("year") or stub.get("year")
    authors_after = work_fields.get("authors") or stub.get("authors") or []

    if title_after and (abstract_after or (year_after and len(authors_after) >= 1)):
        return Decision.PROMOTE
    return Decision.ENRICH_KEEP_STUB


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
) -> Decision:
    """Run one promotion transaction. Raises PromotionError on verify failure."""
    pid = stub["point_id"]

    # A. dedup guard
    real_dup = storage.find_real_by_identifier({
        "doi": work_fields.get("doi") or stub.get("doi"),
        "openalex_id": work_fields.get("openalex_id") or stub.get("openalex_id"),
        "arxiv_id": work_fields.get("arxiv_id") or stub.get("arxiv_id"),
    })
    if real_dup and real_dup != pid:
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
