"""Importable pipeline stage functions shared by the CLI and the Dagster assets.

Each stage is a thin, side-effecting orchestration over src.core.* that returns
a small structured result (counts), not paper data. Paper data lives in Qdrant.
"""

import datetime

from src.core.storage import QdrantStorage
from src.core.crawler import (
    CoreCorpusCollector,
    ACLAnthologyCollector,
    get_acl_venues,
    DBLPCollector,
    get_dblp_venues,
    OpenReviewCollector,
    get_openreview_venues,
    AAOJSCollector,
    get_aaai_venues,
)


async def collect_incremental_stage(days: int = 3, source: str = "all") -> dict[str, int]:
    """Collect new papers from the last `days` days across sources.

    Returns a dict of per-source counts plus a "total" key. Mirrors the logic in
    the collect-incremental CLI command. The collector dedups against existing
    DOIs/IDs, so overlapping daily windows are harmless.
    """
    since_year = (datetime.datetime.now() - datetime.timedelta(days=days)).year
    current_year = datetime.datetime.now().year

    storage = QdrantStorage()
    storage.ensure_collection()
    results: dict[str, int] = {}

    if source in ("all", "openalex"):
        async with CoreCorpusCollector(storage=storage) as collector:
            results["openalex"] = await collector.collect_incremental(days_back=days)

    if source in ("all", "acl"):
        async with ACLAnthologyCollector(storage=storage) as collector:
            count = 0
            for venue in get_acl_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["acl"] = count

    if source in ("all", "dblp"):
        async with DBLPCollector(storage=storage) as collector:
            count = 0
            for venue in get_dblp_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["dblp"] = count

    if source in ("all", "openreview"):
        async with OpenReviewCollector(storage=storage) as collector:
            count = 0
            for venue in get_openreview_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["openreview"] = count

    if source in ("all", "aaai"):
        async with AAOJSCollector(storage=storage) as collector:
            count = 0
            for venue in get_aaai_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["aaai"] = count

    results["total"] = sum(v for k, v in results.items() if k != "total")
    return results
