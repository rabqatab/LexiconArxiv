"""Pure matching logic for OpenAlex-snapshot offline enrichment."""

from dataclasses import dataclass

from src.core.deduplication import Deduplicator
from src.core.crawler.openalex import reconstruct_abstract


@dataclass
class Candidate:
    point_id: str
    year: int | None
    first_author: str | None
    missing_abstract: bool
    missing_refs: bool


@dataclass
class Match:
    candidate: Candidate
    source: str  # "doi" | "title"


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d or None


def _work_first_author(work: dict) -> str | None:
    auths = work.get("authorships") or []
    if not auths:
        return None
    name = (auths[0].get("author") or {}).get("display_name") or ""
    parts = name.strip().split()
    return parts[-1].lower() if parts else None


def build_candidate_index(candidates: list[dict]):
    """Return (doi_map, title_map). doi_map: doi->Candidate; title_map: title_norm->list[Candidate]."""
    doi_map: dict[str, Candidate] = {}
    title_map: dict[str, list[Candidate]] = {}
    for c in candidates:
        cand = Candidate(c["point_id"], c.get("year"), c.get("first_author"),
                         c["missing_abstract"], c["missing_refs"])
        d = _norm_doi(c.get("doi"))
        if d:
            doi_map[d] = cand
        tnorm = Deduplicator.normalize_title(c.get("title") or "")
        if tnorm:
            title_map.setdefault(tnorm, []).append(cand)
    return doi_map, title_map


def _corroborates(work: dict, cand: Candidate) -> bool:
    wy = work.get("publication_year") or work.get("year")
    if wy and cand.year and abs(int(wy) - int(cand.year)) <= 1:
        return True
    wa = _work_first_author(work)
    if wa and cand.first_author and wa == cand.first_author:
        return True
    return False


def match_work(work: dict, doi_map, title_map) -> Match | None:
    d = _norm_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
    if d and d in doi_map:
        return Match(doi_map[d], "doi")
    tnorm = Deduplicator.normalize_title(work.get("title") or "")
    if tnorm and tnorm in title_map:
        for cand in title_map[tnorm]:
            if _corroborates(work, cand):
                return Match(cand, "title")
    return None


def extract_enrichment(work: dict, cand: Candidate) -> dict:
    """Return only the fields this candidate is MISSING (fill-only-missing)."""
    out: dict = {}
    if cand.missing_abstract:
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        if abstract:
            out["abstract"] = abstract
    if cand.missing_refs:
        refs = work.get("referenced_works") or []
        if refs:
            out["referenced_works"] = refs
    return out
