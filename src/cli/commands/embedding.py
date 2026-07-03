"""CLI commands for embedding pipeline."""

import asyncio
import sys
from typing import Callable

import click

from src.cli._logging import logger


async def drain_snapshot_queue(
    storage,
    embedder,
    *,
    embed_batch_size: int = 64,
    chunk_size: int = 500,
    echo: Callable[[str], None] = print,
    priority_filter: Callable[[dict], bool] | None = None,
) -> int:
    """Drain the snapshot-queued point IDs into embedded vectors.

    Uses explicit-ack semantics (peek_all + remove) to survive consumer
    crashes without losing work — see incident 2026-06-30 where a bad
    drain() destroyed 663K entries in 3 seconds. Chunking is doubled up:
    Qdrant retrieve() by IDs blows past request body limits at ~1K items,
    and we ack per-chunk so a crash preserves work-in-progress on the
    remaining chunks.

    Args:
        priority_filter: If provided, only embed papers whose payload
            passes filter(payload). Non-passing items stay unacked in the
            queue for a follow-up drain call. Two-phase pattern:
              ``drain(..., priority_filter=lambda p: (p.get("tier") or 99) <= 1)``
              followed by ``drain(...)`` picks tier 0/1 first, everything
              else after.

    Returns:
        Number of papers successfully embedded in this call.
    """
    from src.core.snapshot import embedding_queue

    queued = embedding_queue.peek_all()
    if not queued:
        return 0

    label = "priority-filtered" if priority_filter else "all"
    echo(f"Consuming {len(queued)} points from snapshot queue ({label})...")
    total_embedded = 0
    total_skipped = 0
    payload_fields = ["title", "abstract", "abstract_structure",
                      "tier", "venue", "year", "cited_by_count"]
    for i in range(0, len(queued), chunk_size):
        chunk = queued[i:i + chunk_size]
        pids = [pid for pid, _ in chunk]
        records = storage.client.retrieve(
            collection_name=storage.collection_name,
            ids=pids,
            with_payload=payload_fields,
            with_vectors=False,
        )

        # Papers we intend to embed this chunk. When priority_filter is set,
        # non-passing items stay unacked in the queue for a follow-up call.
        selected_records = [
            r for r in records
            if priority_filter is None or priority_filter(r.payload or {})
        ]
        papers = [(str(r.id), r.payload or {}) for r in selected_records]

        if papers:
            count = await embedder.embed_and_upsert_batch(
                papers=papers, storage=storage,
                embed_batch_size=embed_batch_size,
            )
            total_embedded += count

        # ACK after successful embed+upsert. Selection semantics:
        #   - No filter → ack the whole chunk (matches missing-record
        #     handling: retrieve() may skip deleted IDs but their queue
        #     entries were live so we clear them anyway).
        #   - With filter → ack only:
        #       (a) records that PASSED the filter and got embedded, PLUS
        #       (b) queue entries whose Qdrant record is missing (dead
        #           payload, same handling as no-filter case).
        #     Records that EXIST but were rejected by the filter stay in
        #     the queue for the follow-up call.
        if priority_filter is None:
            ack_chunk = chunk
        else:
            selected_pids = {str(r.id) for r in selected_records}
            retrieved_pids = {str(r.id) for r in records}
            ack_chunk = [
                (pid, src) for (pid, src) in chunk
                if pid in selected_pids or pid not in retrieved_pids
            ]
            total_skipped += len(chunk) - len(ack_chunk)
        embedding_queue.remove(ack_chunk)

        if total_embedded and total_embedded % 1000 == 0:
            echo(f"  consumed {total_embedded} from queue "
                 f"(of {len(queued)} pending{', ' + str(total_skipped) + ' skipped' if total_skipped else ''})")

    if total_skipped:
        echo(f"Skipped {total_skipped} non-priority items — "
             f"still in queue for a follow-up call.")
    return total_embedded


def register_commands(cli: click.Group):
    @cli.command()
    @click.option("--new-collection", default=None, help="Name for new collection (default: {old}_v2)")
    @click.option("--delete-old", is_flag=True, help="Delete old collection after migration")
    @click.option("--dry-run", is_flag=True, help="Show what would be migrated without doing it")
    def migrate_collection(new_collection, delete_old, dry_run):
        """Migrate payload-only collection to vector-enabled collection.

        Creates a new collection with dense (Qwen3-8B, 1024d) and sparse
        (BM25) vector configs, then copies all points from the old collection.

        Examples:

          uv run python -m src.cli.core_collect migrate-collection

          uv run python -m src.cli.core_collect migrate-collection --delete-old
        """
        from src.core.embedding.migration import CollectionMigrator
        from src.core.constants import get_qdrant_url, get_qdrant_collection

        url = get_qdrant_url()
        old_name = get_qdrant_collection()

        if dry_run:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=url)
            count = client.count(old_name).count
            click.echo(f"Would migrate {count:,} points from '{old_name}' to '{new_collection or old_name + '_v2'}'")
            return

        migrator = CollectionMigrator(
            url=url,
            old_collection=old_name,
            new_collection=new_collection,
        )
        click.echo(f"Migrating '{old_name}' → '{migrator.new_collection}'...")
        stats = migrator.migrate(delete_old=delete_old)

        click.echo(f"\nMigration complete:")
        click.echo(f"  Points migrated: {stats['points_migrated']:,}")
        click.echo(f"  New collection:  {stats['new_collection']}")
        click.echo(f"  Snapshot:        {stats['snapshot_name']}")
        click.echo(f"  Time:            {stats['elapsed_seconds']}s")

        if not delete_old:
            click.echo(f"\n  Old collection '{old_name}' preserved.")
            click.echo(f"  Update QDRANT_COLLECTION={stats['new_collection']} in .env to use new collection.")

    @cli.command()
    @click.option("--batch-size", type=int, default=8, help="Papers per batch (each generates ~9 texts)")
    @click.option("--embed-batch-size", type=int, default=64, help="Max texts per Ollama embed call")
    @click.option("--concurrency", "-p", type=int, default=4, help="Parallel Ollama requests")
    @click.option("--limit", "-n", type=int, default=None, help="Max papers to embed")
    @click.option("--resume/--no-resume", default=True, help="Resume from checkpoint")
    @click.option("--dry-run", is_flag=True, help="Count papers to embed without doing it")
    @click.option("--consume-snapshot-queue", is_flag=True,
                  help="Drain points queued by P2/P3 first; then fall through to the default scroll.")
    @click.option("--priority-tier", type=int, default=None,
                  help="Only embed queued papers with tier <= N (0=top, 1=extended). "
                       "Non-matching items stay in queue for a follow-up call — lets "
                       "search become useful on the highest-quality subset first.")
    def embed_papers(batch_size, embed_batch_size, concurrency, limit, resume, dry_run,
                     consume_snapshot_queue, priority_tier):
        """Embed paper abstracts with section-level + structured-abstract vectors.

        Generates up to 9 dense vectors per paper (abstract, structured-abstract,
        and 7 section-level vectors) plus BM25 sparse vectors.

        Examples:

          uv run python -m src.cli.core_collect embed-papers

          uv run python -m src.cli.core_collect embed-papers -p 8

          uv run python -m src.cli.core_collect embed-papers -n 100

          uv run python -m src.cli.core_collect embed-papers --no-resume
        """
        from src.core.embedding.embedder import PaperEmbedder
        from src.core.storage.base import QdrantStorage
        from src.core.constants import ALL_DENSE_VECTORS

        storage = QdrantStorage()

        if dry_run:
            total = storage.count_papers_for_embedding()
            click.echo(f"Papers to embed: {total:,}")
            return

        # Pre-flight: verify collection has vector config
        try:
            info = storage.client.get_collection(storage.collection_name)
            vectors = info.config.params.vectors or {}
            missing = [v for v in ALL_DENSE_VECTORS if v not in vectors]
            if missing:
                click.echo(
                    f"Error: Collection missing vector configs: {missing}. "
                    "Run: uv run python -m src.cli.core_collect migrate-collection",
                    err=True,
                )
                sys.exit(1)
        except Exception as e:
            click.echo(f"Error: Cannot connect to Qdrant: {e}", err=True)
            sys.exit(1)

        async def run():
            embedder = PaperEmbedder(max_concurrent=concurrency)
            async with embedder:
                # Check model availability
                if not await embedder.check_model_available():
                    click.echo(
                        "Error: Embedding model not found in Ollama. "
                        "Run: ollama pull qwen3-embedding:8b",
                        err=True,
                    )
                    sys.exit(1)

                total_embedded = 0
                offset = None

                if consume_snapshot_queue:
                    if priority_tier is not None:
                        max_tier = priority_tier

                        def _tier_filter(payload: dict) -> bool:
                            # Papers without a tier count as "low priority"
                            # (99 > any real tier) so they wait for the
                            # unfiltered follow-up drain.
                            t = payload.get("tier")
                            return t is not None and t <= max_tier
                    else:
                        _tier_filter = None
                    total_embedded += await drain_snapshot_queue(
                        storage=storage,
                        embedder=embedder,
                        embed_batch_size=embed_batch_size,
                        echo=click.echo,
                        priority_filter=_tier_filter,
                    )

                while True:
                    # skip_embedded=True uses HasVectorCondition to skip
                    # papers that already have dense vectors (resume-safe)
                    papers, next_offset = storage.get_papers_for_embedding(
                        limit=batch_size,
                        offset=offset,
                        skip_embedded=resume,
                    )

                    if not papers:
                        break

                    count = await embedder.embed_and_upsert_batch(
                        papers=papers,
                        storage=storage,
                        embed_batch_size=embed_batch_size,
                    )
                    total_embedded += count

                    if total_embedded % 1000 == 0:
                        click.echo(f"  Embedded {total_embedded:,} papers...")

                    if limit and total_embedded >= limit:
                        break

                    if next_offset is None:
                        break
                    offset = next_offset

                click.echo(f"\nEmbedding complete: {total_embedded:,} papers embedded")

        asyncio.run(run())

    @cli.command()
    @click.option("--collection", required=True, help="Collection name to delete")
    @click.option("--confirm", is_flag=True, help="Confirm deletion")
    def delete_old_collection(collection, confirm):
        """Delete an old Qdrant collection (e.g., lexicon_arxiv, lexicon_arxiv_v2).

        Refuses to delete the currently active collection. Use --confirm to
        actually perform the deletion.

        Examples:

          uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v2

          uv run python -m src.cli.core_collect delete-old-collection --collection lexicon_arxiv_v2 --confirm
        """
        from qdrant_client import QdrantClient
        from src.core.constants import get_qdrant_url, get_qdrant_collection

        current = get_qdrant_collection()
        if collection == current:
            click.echo(f"Error: Cannot delete the active collection '{current}'")
            sys.exit(1)

        client = QdrantClient(url=get_qdrant_url())
        try:
            info = client.get_collection(collection)
            count = info.points_count
        except Exception:
            click.echo(f"Collection '{collection}' does not exist")
            return

        if not confirm:
            click.echo(f"Would delete collection '{collection}' ({count:,} points)")
            click.echo("Run with --confirm to proceed")
            return

        client.delete_collection(collection)
        click.echo(f"Deleted collection '{collection}' ({count:,} points)")
