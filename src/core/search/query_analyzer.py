"""Query analysis: intent detection, HyDE, RAG-Fusion."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

SECTION_KEYWORDS: dict[str, list[str]] = {
    "method": [
        "using",
        "method",
        "approach",
        "technique",
        "algorithm",
        "how to",
        "implementation",
        "architecture",
    ],
    "task": [
        "problem",
        "task",
        "challenge",
        "about",
        "what is",
        "definition",
        "survey",
    ],
    "result": [
        "performance",
        "results",
        "achieves",
        "outperforms",
        "benchmark",
        "evaluation",
        "sota",
        "state of the art",
    ],
    "background": [
        "history",
        "overview",
        "introduction",
        "motivation",
        "why",
    ],
}


def detect_intent(query: str) -> dict:
    """Detect query intent using keyword heuristics.

    Returns:
        dict with keys: target_section (str|None), is_title_search (bool),
        recency_bias (bool).
    """
    q = query.lower()

    # Title search: quoted strings
    is_title = q.startswith('"') and q.endswith('"')

    # Recency bias
    recency = any(w in q for w in ["latest", "recent", "new", "2024", "2025", "2026"])

    # Section detection via keyword scoring
    section: str | None = None
    best_score = 0
    for sec, keywords in SECTION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > best_score:
            best_score = score
            section = sec
    if best_score == 0:
        section = None

    return {
        "target_section": section,
        "is_title_search": is_title,
        "recency_bias": recency,
    }


async def generate_hyde(
    query: str,
    client: httpx.AsyncClient,
    base_url: str,
) -> str | None:
    """Generate a hypothetical abstract via Ollama chat model.

    Uses qwen3:8b to produce a short abstract that would answer the
    research query.  Returns *None* on any failure so callers can
    gracefully skip the HyDE pathway.
    """
    try:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": "qwen3:8b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an academic research assistant. Write a "
                            "short abstract (3-4 sentences) for a hypothetical "
                            "paper that would answer this research question. "
                            "Be specific and use technical terminology."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "stream": False,
                "think": False,  # qwen3 thinking eats the 10s budget -> empty output
                "options": {"temperature": 0.7, "num_predict": 200},
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    except Exception as e:
        logger.warning("HyDE generation failed: %s", e)
        return None


async def generate_query_variants(
    query: str,
    client: httpx.AsyncClient,
    base_url: str,
    n: int = 3,
) -> list[str]:
    """Generate *n* query reformulations via LLM (RAG-Fusion).

    Returns up to *n* variant queries.  On failure returns an empty list
    so the pipeline falls back to the original query only.
    """
    try:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": "qwen3:8b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Generate exactly {n} different search queries "
                            "for finding academic papers about the given topic. "
                            "Return ONLY the queries, one per line. "
                            "No numbering, no explanation."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "stream": False,
                "think": False,  # qwen3 thinking eats the 10s budget -> empty output
                "options": {"temperature": 0.8, "num_predict": 200},
            },
            timeout=10.0,
        )
        response.raise_for_status()
        text = response.json()["message"]["content"]
        variants = [line.strip() for line in text.strip().split("\n") if line.strip()]
        return variants[:n]
    except Exception as e:
        logger.warning("Query variant generation failed: %s", e)
        return []


async def generate_query_decomposition(
    query: str,
    client: httpx.AsyncClient,
    base_url: str,
    n: int = 3,
) -> list[str]:
    """Decompose a multi-part query into independent sub-queries.

    Unlike RAG-Fusion (which *reformulates* the same intent), this splits a
    comparative or compound question — "BERT vs GPT for code" ->
    ["BERT for code", "GPT for code", ...] — so each sub-query can hit different
    section vectors and the union is fused. Returns [] on failure (pipeline
    falls back to the original query only). A single-intent query legitimately
    decomposes to itself; callers dedupe against the original.
    """
    try:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": "qwen3:8b",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Break the research query into at most {n} independent "
                            "sub-questions, each self-contained. If the query is "
                            "already a single question, return it unchanged. Return "
                            "ONLY the sub-questions, one per line, no numbering."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "stream": False,
                "think": False,  # qwen3 thinking eats the 10s budget -> empty output
                "options": {"temperature": 0.3, "num_predict": 200},
            },
            timeout=10.0,
        )
        response.raise_for_status()
        text = response.json()["message"]["content"]
        subs = [line.strip() for line in text.strip().split("\n") if line.strip()]
        # drop an echo of the original (single-intent case) — no value re-searching it
        subs = [s for s in subs if s.lower() != query.strip().lower()]
        return subs[:n]
    except Exception as e:
        logger.warning("Query decomposition failed: %s", e)
        return []


def adaptive_rrf_weights(query: str) -> tuple[float, float]:
    """Heuristic (dense_weight, bm25_weight) from query shape, summing to ~2.0.

    Short / keyword-ish / quoted / acronym-heavy queries favour BM25 lexical
    match; long / natural-language queries favour dense semantic match. Weights
    scale each modality's candidate share into RRF (see service._adaptive_limits).

    ponytail: length + acronym + quote heuristic, no classifier. Upgrade to a
    learned query-type model only if A/B shows this mis-weights real traffic.
    """
    q = query.strip()
    tokens = q.split()
    n = len(tokens)
    quoted = '"' in q
    # acronym-heavy: uppercase tokens like BM25, RRF, GPT, BERT
    acronyms = sum(1 for t in tokens if t.isupper() and len(t) >= 2)
    lexical = quoted or (n <= 3) or (acronyms >= max(1, n // 2))
    if lexical:
        return (0.7, 1.3)   # tilt to BM25
    if n >= 12:
        return (1.4, 0.6)   # long NL -> tilt to dense
    return (1.0, 1.0)       # balanced
