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
