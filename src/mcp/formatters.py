"""LLM-friendly formatters for search results and paper details."""


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
        author_str = ", ".join(authors[:3])
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
        lines.append(f"**Authors:** {', '.join(authors)}")
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
