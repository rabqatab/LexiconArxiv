"""Pure matching logic for OpenAlex-snapshot offline enrichment."""

from dataclasses import dataclass, field

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


@dataclass
class StubIndex:
    doi_map: dict[str, str] = field(default_factory=dict)
    arxiv_map: dict[str, str] = field(default_factory=dict)
    openalex_map: dict[str, str] = field(default_factory=dict)
    title_map: dict[str, list[str]] = field(default_factory=dict)


def build_stub_index(stubs: list[dict]) -> StubIndex:
    idx = StubIndex()
    for stub in stubs:
        pid = stub["point_id"]
        itype = stub.get("identifier_type")
        ident = stub.get("identifier") or ""

        if itype == "doi":
            doi = _norm_doi(ident[4:] if ident.startswith("doi:") else stub.get("doi") or ident)
            if doi:
                idx.doi_map.setdefault(doi, pid)
        elif itype == "arxiv":
            arxiv = ident[len("arXiv:"):] if ident.lower().startswith("arxiv:") else ident
            if arxiv:
                idx.arxiv_map.setdefault(arxiv, pid)
        elif itype == "openalex":
            wid = ident.rsplit("/", 1)[-1].replace("openalex:", "")
            if wid:
                idx.openalex_map.setdefault(wid, pid)

        # also index by title if the stub has one
        title = stub.get("title")
        if title:
            norm = Deduplicator.normalize_title(title)
            if norm:
                idx.title_map.setdefault(norm, []).append(pid)

        # alternate identifiers
        for alt_type, alt_val in (stub.get("alternate_identifiers") or {}).items():
            if alt_type == "doi":
                doi = _norm_doi(alt_val)
                if doi:
                    idx.doi_map.setdefault(doi, pid)
            elif alt_type == "arxiv":
                idx.arxiv_map.setdefault(alt_val, pid)
            elif alt_type == "openalex":
                idx.openalex_map.setdefault(alt_val, pid)
    return idx


def match_work_for_stubs(
    work: dict,
    index: StubIndex,
    *,
    all_stubs_by_id: dict[str, dict],
) -> dict | None:
    # DOI first
    doi = _norm_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
    if doi and (pid := index.doi_map.get(doi)):
        return all_stubs_by_id.get(pid)

    # arXiv
    arxiv = (work.get("ids") or {}).get("arxiv")
    if arxiv and (pid := index.arxiv_map.get(arxiv)):
        return all_stubs_by_id.get(pid)

    # OpenAlex ID
    wid = (work.get("id") or "").rsplit("/", 1)[-1]
    if wid and (pid := index.openalex_map.get(wid)):
        return all_stubs_by_id.get(pid)

    # Title with corroboration
    title = work.get("title") or work.get("display_name")
    if not title:
        return None
    norm = Deduplicator.normalize_title(title)
    if not norm:
        return None
    for pid in index.title_map.get(norm, []):
        stub = all_stubs_by_id.get(pid)
        if not stub:
            continue
        # build a Candidate-like view for the corroboration check
        stub_year = stub.get("year")
        stub_author = _first_author_surname_of_stub(stub)

        # For stubs with no year/author metadata, accept if title matches (no corroboration needed)
        if stub_year is None and stub_author is None:
            return stub

        # Otherwise require corroboration
        cand = type("S", (), {
            "year": stub_year,
            "first_author": stub_author,
        })
        if _corroborates(work, cand):
            return stub
    return None


def _first_author_surname_of_stub(stub: dict) -> str | None:
    authors = stub.get("authors") or []
    if not authors:
        return None
    name = authors[0].get("display_name") or ""
    return name.strip().split()[-1].lower() if name else None
