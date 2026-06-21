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


def _norm_openalex_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.rsplit("/", 1)[-1]


def _norm_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def extract_full_record(work: dict) -> dict[str, Any]:
    """Build a full payload dict suitable for a NEW corpus point.

    P2 (promotion) and P3 (injection) both call this. The caller is
    responsible for adding provenance keys (promoted_from_stub, etc.).
    """
    out: dict[str, Any] = {}

    if title := (work.get("title") or work.get("display_name")):
        out["title"] = title
    if doi := _norm_doi(work.get("doi")):
        out["doi"] = doi
    if oa := _norm_openalex_id(work.get("id")):
        out["openalex_id"] = oa
    if year := work.get("publication_year"):
        out["year"] = year
    if pdate := work.get("publication_date"):
        out["publication_date"] = pdate
    if t := work.get("type"):
        out["type"] = t
    if work.get("is_retracted") is True:
        out["is_retracted"] = True

    inv = work.get("abstract_inverted_index")
    if inv:
        abs_text = reconstruct_abstract(inv)
        if abs_text:
            out["abstract"] = abs_text

    authors = [
        {"display_name": (a.get("author") or {}).get("display_name", "")}
        for a in (work.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    ]
    if authors:
        out["authors"] = authors

    if venue := ((work.get("primary_location") or {}).get("source") or {}).get("display_name"):
        out["venue"] = venue

    if refs := work.get("referenced_works"):
        out["referenced_works"] = list(refs)

    arxiv_id = (work.get("ids") or {}).get("arxiv") or _arxiv_from_doi(out.get("doi"))
    if arxiv_id:
        out["arxiv_id"] = arxiv_id

    # fold in all P1 metadata fields
    out.update(extract_p1_fields(work, existing_payload=None))
    return out


def _arxiv_from_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    # arXiv DOIs look like 10.48550/arXiv.2401.12345
    marker = "10.48550/arxiv."
    if doi.startswith(marker):
        return doi[len(marker):]
    return None
