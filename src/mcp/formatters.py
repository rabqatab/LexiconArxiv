"""LLM-friendly formatters for search results and paper details."""

from __future__ import annotations


def _author_name(a) -> str:
    """Coerce an author entry to a display string.

    P2 promotion writes OpenAlex `authorships` payload — a list of dicts
    keyed by `display_name`, `author.display_name`, etc. Old crawler paths
    wrote plain strings. This helper accepts either. Fixed 2026-07-03 for
    the `sequence item 0: expected str instance, dict found` incident.
    """
    if a is None:
        return ""
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        # Try common name-carrying keys, in decreasing specificity
        for k in ("display_name", "name"):
            v = a.get(k)
            if v:
                return str(v)
        author = a.get("author")
        if isinstance(author, dict):
            v = author.get("display_name") or author.get("name")
            if v:
                return str(v)
    return ""


def format_search_results(results: dict, max_results: int = 10) -> str:
    """Format search results as a numbered list for LLM consumption.

    Args:
        results: Search results dict from SearchService.search(), containing
                 'results', 'total', 'query_time_ms', and 'search_mode'.
        max_results: Maximum number of results to include in output.

    Returns:
        Formatted text string with numbered paper list.
    """
    items = results.get("results", [])
    total = results.get("total", 0)
    query_time_ms = results.get("query_time_ms", 0)
    search_mode = results.get("search_mode", "unknown")

    if not items:
        return "No results found."

    lines = [
        f"Found {total} papers ({query_time_ms}ms, {search_mode}). "
        f"Showing top {min(len(items), max_results)}:\n"
    ]

    for i, item in enumerate(items[:max_results], 1):
        title = item.get("title", "Untitled")
        authors = item.get("authors", [])
        author_names = [n for n in (_author_name(a) for a in authors[:3]) if n]
        author_str = ", ".join(author_names)
        if len(authors) > 3:
            author_str += f" et al. ({len(authors)} authors)"
        venue = item.get("venue", "")
        year = item.get("year", "")
        tier = item.get("tier")
        citations = item.get("citation_count", 0)
        keywords = item.get("keywords", [])
        score = item.get("score", 0.0)

        lines.append(f"{i}. **{title}**")
        if author_str:
            lines.append(f"   Authors: {author_str}")
        venue_parts = []
        if venue:
            venue_parts.append(venue)
        if year:
            venue_parts.append(str(year))
        if venue_parts:
            lines.append(f"   Venue: {' '.join(venue_parts)}")
        if tier is not None:
            lines.append(f"   Tier: {tier}")
        lines.append(f"   Citations: {citations}")
        if keywords:
            lines.append(f"   Keywords: {', '.join(keywords[:8])}")
        lines.append(f"   Score: {score}")
        lines.append(f"   ID: {item.get('id', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def format_paper_detail(paper: dict) -> str:
    """Format a single paper's full details as markdown for LLM consumption.

    Args:
        paper: Paper detail dict from SearchService.get_paper().

    Returns:
        Markdown-formatted paper detail string.
    """
    if paper is None:
        return "Paper not found."

    title = paper.get("title", "Untitled")
    lines = [f"# {title}\n"]

    # Identifiers
    ids = []
    if paper.get("id"):
        ids.append(f"ID: {paper['id']}")
    if paper.get("doi"):
        ids.append(f"DOI: {paper['doi']}")
    if paper.get("arxiv_id"):
        ids.append(f"arXiv: {paper['arxiv_id']}")
    if ids:
        lines.append(" | ".join(ids))
        lines.append("")

    # Authors
    authors = paper.get("authors", [])
    if authors:
        author_names = [n for n in (_author_name(a) for a in authors) if n]
        if author_names:
            lines.append(f"**Authors:** {', '.join(author_names)}")
            lines.append("")

    # Venue and year
    venue = paper.get("venue", "")
    year = paper.get("year", "")
    if venue or year:
        venue_str = f"{venue} {year}".strip() if venue else str(year)
        lines.append(f"**Venue:** {venue_str}")
        lines.append("")

    # Tier
    tier = paper.get("tier")
    if tier is not None:
        lines.append(f"**Tier:** {tier}")
        lines.append("")

    # Citation metrics
    citations = paper.get("citation_count", 0)
    pagerank = paper.get("pagerank")
    metrics = [f"Citations: {citations}"]
    if pagerank is not None:
        metrics.append(f"PageRank: {pagerank:.6f}")
    ref_count = paper.get("reference_count", 0)
    cited_by_count = paper.get("cited_by_count", 0)
    metrics.append(f"References: {ref_count}")
    metrics.append(f"Cited by: {cited_by_count}")
    lines.append(f"**Metrics:** {' | '.join(metrics)}")
    lines.append("")

    # Flags
    flags = []
    if paper.get("is_core"):
        flags.append("Core")
    if paper.get("is_stub"):
        flags.append("Stub")
    if flags:
        lines.append(f"**Flags:** {', '.join(flags)}")
        lines.append("")

    # Abstract
    abstract = paper.get("abstract")
    if abstract:
        lines.append("## Abstract\n")
        lines.append(abstract)
        lines.append("")

    # Structured abstract
    abstract_structure = paper.get("abstract_structure")
    if abstract_structure and isinstance(abstract_structure, dict):
        lines.append("## Structured Abstract\n")
        for section, text in abstract_structure.items():
            lines.append(f"**{section}:** {text}")
        lines.append("")

    # Keywords
    keywords = paper.get("keywords", [])
    if keywords:
        lines.append(f"**Keywords:** {', '.join(keywords)}")
        lines.append("")

    # Structured keywords
    keywords_structured = paper.get("keywords_structured")
    if keywords_structured and isinstance(keywords_structured, dict):
        lines.append("## Structured Keywords\n")
        for category, kws in keywords_structured.items():
            if isinstance(kws, list):
                lines.append(f"- **{category}:** {', '.join(kws)}")
            else:
                lines.append(f"- **{category}:** {kws}")
        lines.append("")

    # Code repositories
    code_repos = paper.get("code_repositories", [])
    code_url = paper.get("code_url")
    if code_repos:
        lines.append("## Code Repositories\n")
        for repo in code_repos:
            if isinstance(repo, dict):
                url = repo.get("url", "")
                lines.append(f"- {url}")
            else:
                lines.append(f"- {repo}")
        lines.append("")
    elif code_url:
        lines.append(f"**Code:** {code_url}")
        lines.append("")

    # PDF URL
    pdf_url = paper.get("pdf_url")
    if pdf_url:
        lines.append(f"**PDF:** {pdf_url}")
        lines.append("")

    return "\n".join(lines)


def format_corpus_stats(
    *,
    total: int,
    real: int,
    stubs: int,
    venue_stats: dict[str, int],
    top_venues: int = 30,
) -> str:
    """Format corpus statistics with a bounded venue list.

    Full dumps blow the MCP response past 1.6MB / 38K lines on a 3.6M-point
    corpus with ~thousands of unique venues (2026-07-03 incident). Cap at
    top-N by count and report the tail as a single summary line so callers
    still see the long-tail shape without paying to render it.
    """
    n_venues = len(venue_stats)
    top_venues = max(0, min(top_venues, n_venues))
    sorted_venues = sorted(venue_stats.items(), key=lambda x: -x[1])

    lines = [
        "# LexiconArxiv Corpus Statistics\n",
        f"**Total points:** {total:,}",
        f"**Real papers:** {real:,}",
        f"**Stub papers:** {stubs:,}",
        f"**Distinct venues:** {n_venues:,}",
        "",
    ]

    if top_venues > 0:
        lines.append(f"## Top {top_venues} Venues (of {n_venues:,})\n")
        for venue, count in sorted_venues[:top_venues]:
            lines.append(f"- {venue}: {count:,}")

    remaining = n_venues - top_venues
    if remaining > 0:
        tail_sum = sum(c for _, c in sorted_venues[top_venues:])
        lines.append("")
        lines.append(
            f"_…and {remaining:,} more venues covering {tail_sum:,} papers._"
        )

    lines.append("")
    return "\n".join(lines)


def format_research_results(data: dict) -> str:
    """Format research_topic() output as markdown for LLM consumption.

    Args:
        data: Result dict from research_topic(), containing query, papers,
              trends, summary, and query_time_ms.

    Returns:
        Markdown-formatted research overview string.
    """
    query = data.get("query", "")
    papers = data.get("papers", [])
    trends = data.get("trends", [])
    summary = data.get("summary", {})
    query_time_ms = data.get("query_time_ms", 0)

    if not papers:
        return f"# Research: {query}\n\nNo papers found for this topic."

    lines: list[str] = [f"# Research: {query}\n"]

    # ----- Key Papers -----
    lines.append(f"## Key Papers ({len(papers)} most notable & relevant)\n")

    for i, paper in enumerate(papers, 1):
        title = paper.get("title", "Untitled")
        authors = paper.get("authors", [])
        author_names = [n for n in (_author_name(a) for a in authors[:3]) if n]
        author_str = ", ".join(author_names)
        if len(authors) > 3:
            author_str += " et al."

        venue = paper.get("venue", "")
        year = paper.get("year", "")
        tier = paper.get("tier")
        citations = paper.get("citation_count", 0)
        relevance = paper.get("relevance_score", 0.0)
        notable = paper.get("notable_score", 0.0)
        combined = paper.get("combined_score", 0.0)
        keywords = paper.get("keywords", [])

        venue_year = f"{venue} {year}".strip() if venue else str(year) if year else ""
        if tier is not None:
            tier_str = f"Tier {tier}"
        else:
            tier_str = ""

        lines.append(f'{i}. "{title}"')
        meta_parts = []
        if author_str:
            meta_parts.append(author_str)
        if venue_year:
            meta_parts.append(venue_year)
        if tier_str:
            meta_parts.append(tier_str.strip())
        meta_parts.append(f"{citations:,} citations")
        lines.append(f"   {' | '.join(meta_parts)}")
        lines.append(
            f"   Combined score: {combined:.2f} "
            f"(relevance: {relevance:.2f}, notable: {notable:.2f})"
        )
        if keywords:
            lines.append(f"   Keywords: {', '.join(keywords[:6])}")
        lines.append("")

    # ----- Trends -----
    if trends:
        lines.append("## Trends in This Area\n")

        rising_parts = []
        for t in trends[:8]:
            keyword = t.get("keyword", "")
            growth = t.get("growth_rate", 0.0)
            if growth > 1.0:
                pct = int((growth - 1.0) * 100)
                rising_parts.append(f"{keyword} (+{pct}%)")
            elif growth == 0.0:
                continue
            else:
                rising_parts.append(keyword)

        if rising_parts:
            lines.append(f"Rising: {', '.join(rising_parts)}")

        # Peak years from the papers
        years = [p.get("year") for p in papers if p.get("year")]
        if years:
            year_min = min(years)
            year_max = max(years)
            lines.append(f"Peak years: {year_min}-{year_max} (majority of papers)")
        lines.append("")

    # ----- Summary -----
    lines.append("## Summary\n")

    total_found = summary.get("total_found", len(papers))
    lines.append(f"- {total_found} total papers found")

    year_range = summary.get("year_range", [])
    if year_range and len(year_range) == 2:
        lines.append(f"- Years: {year_range[0]}-{year_range[1]}")

    top_venues = summary.get("top_venues", [])
    if top_venues:
        venue_strs = [f"{v['venue']} ({v['count']})" for v in top_venues[:6]]
        lines.append(f"- Top venues: {', '.join(venue_strs)}")

    top_authors = summary.get("top_authors", [])
    if top_authors:
        author_strs = [f"{a['author']} ({a['count']})" for a in top_authors[:6]]
        lines.append(f"- Top authors: {', '.join(author_strs)}")

    lines.append(f"\n_Query time: {query_time_ms}ms_")

    return "\n".join(lines)
