"""Run keyword extraction + abstract labeling on 100 papers and export results.

Fetches 100 papers with abstracts from Qdrant, runs both pipelines via Gemini,
and saves original data + processed results under data/test_data/.
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

import pysbd
from qdrant_client import QdrantClient

from src.core.constants import get_qdrant_url, get_qdrant_collection
from src.core.keyword.extractor import KeywordExtractor
from src.core.labeling import AbstractLabeler
from src.core.labeling.llm_base import format_numbered_sentences

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

LIMIT = 100
OUTPUT_DIR = Path("data/test_data")
_segmenter = pysbd.Segmenter(language="en", clean=False)


def fetch_papers(limit: int) -> list[dict]:
    """Fetch papers with non-empty abstracts from Qdrant."""
    from qdrant_client.http import models

    client = QdrantClient(url=get_qdrant_url())
    collection = get_qdrant_collection()

    results, _ = client.scroll(
        collection_name=collection,
        scroll_filter=models.Filter(
            must_not=[
                models.IsNullCondition(
                    is_null=models.PayloadField(key="abstract"),
                ),
                models.FieldCondition(
                    key="abstract",
                    match=models.MatchValue(value=""),
                ),
            ],
        ),
        limit=limit,
        with_payload=["title", "abstract"],
    )

    papers = []
    for p in results:
        papers.append({
            "id": str(p.id),
            "title": p.payload.get("title", ""),
            "abstract": p.payload.get("abstract", ""),
        })
    return papers


async def run_pipelines(papers: list[dict]) -> list[dict]:
    """Run keyword extraction + abstract labeling on all papers."""
    # Initialize extractors
    kw_extractor = KeywordExtractor(
        use_llm=True, llm_backend="gemini", use_keybert=False, use_judge=False,
    )
    labeler = AbstractLabeler(llm_backend="gemini")

    results = []
    total = len(papers)

    for i, paper in enumerate(papers, 1):
        title = paper["title"]
        abstract = paper["abstract"]
        pid = paper["id"]

        # Keyword extraction
        keywords, kw_source, structured_categories = await kw_extractor.extract_pipeline_with_source(
            title, abstract
        )

        # Abstract labeling
        structure, label_source = await labeler.label_abstract(title, abstract)

        # Sentence splitting (for reference)
        clean = abstract.replace("\\n", " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        sentences = [s.strip() for s in _segmenter.segment(clean) if s.strip()]

        results.append({
            "id": pid,
            "title": title,
            "abstract": abstract,
            "sentences": sentences,
            "keywords": keywords,
            "keyword_source": kw_source,
            "keyword_categories": structured_categories,
            "abstract_structure": structure,
            "abstract_structure_source": label_source,
        })

        if i % 10 == 0 or i == total:
            logger.info(f"Processed {i}/{total} papers")

    await kw_extractor.close()
    await labeler.close()
    return results


def save_results(papers: list[dict], results: list[dict]) -> None:
    """Save original and processed data."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Original data
    original_path = OUTPUT_DIR / "pipeline_100_original.json"
    with open(original_path, "w") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved original data: {original_path} ({len(papers)} papers)")

    # Processed data
    processed_path = OUTPUT_DIR / "pipeline_100_processed.json"
    with open(processed_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved processed data: {processed_path} ({len(results)} papers)")

    # Summary stats
    kw_success = sum(1 for r in results if r["keywords"])
    label_success = sum(1 for r in results if r["abstract_structure"])
    total_sentences = sum(len(r["sentences"]) for r in results)
    avg_sentences = total_sentences / len(results) if results else 0
    avg_keywords = sum(len(r["keywords"]) for r in results) / len(results) if results else 0

    logger.info(f"\n{'='*60}")
    logger.info(f"Pipeline Results Summary ({len(results)} papers)")
    logger.info(f"{'='*60}")
    logger.info(f"Keyword extraction:  {kw_success}/{len(results)} successful")
    logger.info(f"Abstract labeling:   {label_success}/{len(results)} successful")
    logger.info(f"Total sentences:     {total_sentences}")
    logger.info(f"Avg sentences/paper: {avg_sentences:.1f}")
    logger.info(f"Avg keywords/paper:  {avg_keywords:.1f}")


async def main():
    logger.info(f"Fetching {LIMIT} papers from Qdrant...")
    papers = fetch_papers(LIMIT)
    logger.info(f"Fetched {len(papers)} papers")

    logger.info("Running keyword extraction + abstract labeling pipelines...")
    results = await run_pipelines(papers)

    save_results(papers, results)


if __name__ == "__main__":
    asyncio.run(main())
