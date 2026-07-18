"""Pure matching logic for OpenAlex-snapshot offline enrichment."""

from dataclasses import dataclass, field

from src.core.deduplication import Deduplicator


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


def _corroborates(work: dict, cand) -> bool:
    """cand needs .year and .first_author (duck-typed; see match_work_for_stubs)."""
    wy = work.get("publication_year") or work.get("year")
    if wy and cand.year and abs(int(wy) - int(cand.year)) <= 1:
        return True
    wa = _work_first_author(work)
    if wa and cand.first_author and wa == cand.first_author:
        return True
    return False


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

        # Index by title. Clean stubs carry it in `title`; GROBID reference
        # stubs (identifier_type == "title") leave `title` empty and keep the
        # raw title in `identifier` as "TITLE:<text>" — derive it so those
        # ~750K stubs are matchable at all (they were invisible to the index).
        title = stub.get("title")
        if not title and itype == "title" and ident:
            raw = ident[6:] if ident[:6].upper() == "TITLE:" else ident
            # ponytail: 4-word floor — bare GROBID fragments ("related work")
            # would exact-match generic snapshot titles with no year/author to
            # corroborate. Real titles clear it easily.
            if len(raw.split()) >= 4:
                title = raw
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
