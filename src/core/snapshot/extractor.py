"""Pull payload-shaped fields from a single OpenAlex work dict.

Every function is fill-only-missing aware: if `existing_payload` already
contains a non-empty value for a field, that field is omitted from the
returned dict so the caller's batch write never overwrites it.
"""
from typing import Any

from src.core.crawler.openalex import reconstruct_abstract


def _has_value(existing: dict | None, key: str) -> bool:
    if not existing:
        return False
    v = existing.get(key)
    if v is None:
        return False
    if v == "" or v == [] or v == {}:
        return False
    return True


def _orcid_map(work: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in work.get("authorships") or []:
        au = a.get("author") or {}
        name = au.get("display_name")
        orcid = au.get("orcid")
        if name and orcid:
            out[name] = orcid
    return out


def extract_p1_fields(work: dict, existing_payload: dict | None = None) -> dict[str, Any]:
    """Return ONLY the metadata fields that are missing in existing_payload."""
    out: dict[str, Any] = {}
    existing = existing_payload or {}

    # scalars
    for key in ("cited_by_count", "fwci", "language"):
        if not _has_value(existing, key):
            v = work.get(key)
            if v is not None:  # 0 is a real value; None is "unknown"
                out[key] = v

    # nested objects / arrays — emit only if non-empty
    for key in (
        "citation_normalized_percentile",
        "counts_by_year",
        "concepts",
        "topics",
        "primary_topic",
        "sustainable_development_goals",
        "funders",
        "institutions",
        "mesh",
        "open_access",
    ):
        if not _has_value(existing, key):
            v = work.get(key)
            if v:  # non-empty
                out[key] = v

    # best_oa_pdf_url is nested
    if not _has_value(existing, "best_oa_pdf_url"):
        url = (work.get("best_oa_location") or {}).get("pdf_url")
        if url:
            out["best_oa_pdf_url"] = url

    # orcid_map from authorships
    if not _has_value(existing, "orcid_map"):
        m = _orcid_map(work)
        if m:
            out["orcid_map"] = m

    return out
