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
