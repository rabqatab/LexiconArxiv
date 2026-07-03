"""L3 regression net for the 2026-06-30 663K-entry data-loss incident.

Old `drain()` cleared the queue file before the consumer had processed the
items; a Qdrant 400 on the very next line destroyed all 663K entries. The
replacement is `drain_snapshot_queue()` — peek_all + per-chunk retrieve +
per-chunk remove (explicit ack). These tests lock in the crash-safety
contract that the incident postmortem committed us to:

  1. A consumer crash mid-batch does NOT lose unprocessed items.
  2. A resume picks up only the unprocessed items — no re-processing.
  3. Qdrant retrieve() is called in chunks, not a single N-item call.
  4. Missing records (deleted between queue and retrieve) are silently
     acked, not re-queued forever.
"""

from types import SimpleNamespace

import pytest

from src.cli.commands.embedding import drain_snapshot_queue
from src.core.snapshot import embedding_queue


class FakeStorage:
    """Records retrieve() calls; returns SimpleNamespace(id, payload) records."""

    collection_name = "test-collection"

    def __init__(self, records: dict):
        self._records = records  # point_id -> payload
        self.retrieve_calls: list[list[str]] = []
        self.client = self  # storage.client.retrieve()

    def retrieve(self, *, collection_name, ids, with_payload, with_vectors):
        self.retrieve_calls.append(list(ids))
        return [
            SimpleNamespace(id=pid, payload=self._records[pid])
            for pid in ids
            if pid in self._records
        ]


class FakeEmbedder:
    """Records batches; can be induced to raise on the Nth batch."""

    def __init__(self, fail_on_batch: int | None = None):
        self.batches_embedded: list[list[str]] = []
        self._fail_on_batch = fail_on_batch

    async def embed_and_upsert_batch(self, *, papers, storage, embed_batch_size):
        if (
            self._fail_on_batch is not None
            and len(self.batches_embedded) == self._fail_on_batch
        ):
            raise RuntimeError("simulated embedder crash")
        self.batches_embedded.append([pid for pid, _ in papers])
        return len(papers)


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    """Point the embedding_queue at a per-test tmpdir."""
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_drain_happy_path_empties_the_queue(isolated_queue):
    for i in range(3):
        embedding_queue.append(f"pid-{i}", "source")

    storage = FakeStorage({f"pid-{i}": {"title": f"T{i}"} for i in range(3)})
    embedder = FakeEmbedder()

    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
    )

    assert total == 3
    assert embedding_queue.peek_all() == []


@pytest.mark.asyncio
async def test_drain_survives_mid_batch_crash(isolated_queue):
    """CORE INCIDENT REGRESSION: consumer crashes on chunk #2. Chunk #1
    items are acked (removed). Chunk #2 items MUST stay in the queue for
    retry — the entire failure mode of the 663K-loss incident."""
    for i in range(10):
        embedding_queue.append(f"pid-{i}", "source")

    storage = FakeStorage({f"pid-{i}": {} for i in range(10)})
    embedder = FakeEmbedder(fail_on_batch=1)  # raise on 2nd chunk

    with pytest.raises(RuntimeError, match="simulated embedder crash"):
        await drain_snapshot_queue(
            storage=storage, embedder=embedder, chunk_size=5, echo=lambda _: None,
        )

    remaining = embedding_queue.peek_all()
    remaining_pids = {pid for pid, _ in remaining}
    # First 5 processed (removed); last 5 preserved.
    assert remaining_pids == {f"pid-{i}" for i in range(5, 10)}


@pytest.mark.asyncio
async def test_drain_resumes_cleanly_after_partial_crash(isolated_queue):
    """After a crash, a fresh drain call picks up only unprocessed items —
    no re-processing, no missing items."""
    for i in range(10):
        embedding_queue.append(f"pid-{i}", "source")

    storage = FakeStorage({f"pid-{i}": {} for i in range(10)})
    embedder1 = FakeEmbedder(fail_on_batch=1)
    with pytest.raises(RuntimeError):
        await drain_snapshot_queue(
            storage=storage, embedder=embedder1, chunk_size=5, echo=lambda _: None,
        )

    embedder2 = FakeEmbedder()
    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder2, chunk_size=5, echo=lambda _: None,
    )

    assert total == 5
    assert embedding_queue.peek_all() == []

    processed = {pid for batch in embedder1.batches_embedded for pid in batch}
    processed |= {pid for batch in embedder2.batches_embedded for pid in batch}
    # Every point processed exactly once across the two runs
    assert processed == {f"pid-{i}" for i in range(10)}
    total_calls = sum(
        len(b) for b in embedder1.batches_embedded + embedder2.batches_embedded
    )
    assert total_calls == 10  # no duplicates


@pytest.mark.asyncio
async def test_drain_empty_queue_is_noop(isolated_queue):
    storage = FakeStorage({})
    embedder = FakeEmbedder()

    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder, echo=lambda _: None,
    )

    assert total == 0
    assert embedder.batches_embedded == []
    assert storage.retrieve_calls == []


@pytest.mark.asyncio
async def test_drain_chunks_qdrant_retrieve(isolated_queue):
    """Regression for "663K IDs blow Qdrant request body limit": verify
    retrieve() is called in bounded chunks, never as one giant call."""
    for i in range(2500):
        embedding_queue.append(f"pid-{i}", "source")

    storage = FakeStorage({f"pid-{i}": {} for i in range(2500)})
    embedder = FakeEmbedder()

    await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=500, echo=lambda _: None,
    )

    # 2500 / 500 = 5 chunked retrieve calls
    assert len(storage.retrieve_calls) == 5
    for chunk_ids in storage.retrieve_calls:
        assert len(chunk_ids) <= 500


@pytest.mark.asyncio
async def test_drain_acks_missing_records(isolated_queue):
    """Points that exist in the queue but not in Qdrant (edge case:
    deleted between queue-write and retrieve) get acked in the whole-chunk
    remove(), so they don't accumulate as un-embeddable zombies."""
    for i in range(5):
        embedding_queue.append(f"pid-{i}", "source")

    # Only 3 of 5 records exist
    storage = FakeStorage({f"pid-{i}": {} for i in range(3)})
    embedder = FakeEmbedder()

    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
    )

    # Only 3 embedded (the ones that exist)
    assert total == 3
    # But whole chunk acked — nothing left dangling
    assert embedding_queue.peek_all() == []


# ---------------------------------------------------------------------------
# priority_filter — tier-based two-phase drain (design D)
# ---------------------------------------------------------------------------


def _tier_le(max_tier: int):
    """Match the CLI's tier filter.

    Do NOT use ``(p.get("tier") or 99) <= max_tier`` — Python's ``0 or 99``
    is 99 because 0 is falsy, so a tier-0 paper would be treated as
    low-priority. The CLI uses this shape for the same reason.
    """
    def _f(p: dict) -> bool:
        t = p.get("tier")
        return t is not None and t <= max_tier
    return _f


@pytest.mark.asyncio
async def test_drain_with_priority_filter_only_embeds_matching(isolated_queue):
    """Records passing the filter get embedded; non-passing records
    stay unacked in the queue for a follow-up drain call."""
    for i in range(6):
        embedding_queue.append(f"pid-{i}", "source")

    # Half tier 0 (priority), half tier 2 (not priority)
    storage = FakeStorage({
        "pid-0": {"tier": 0}, "pid-1": {"tier": 0}, "pid-2": {"tier": 0},
        "pid-3": {"tier": 2}, "pid-4": {"tier": 2}, "pid-5": {"tier": 2},
    })
    embedder = FakeEmbedder()

    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
        priority_filter=_tier_le(1),
    )

    assert total == 3
    remaining_pids = {pid for pid, _ in embedding_queue.peek_all()}
    assert remaining_pids == {"pid-3", "pid-4", "pid-5"}


@pytest.mark.asyncio
async def test_drain_two_phase_drains_everything(isolated_queue):
    """The intended usage: priority pass first, then unfiltered pass.
    Together every paper is embedded exactly once, priority-first order."""
    for i in range(6):
        embedding_queue.append(f"pid-{i}", "source")
    storage = FakeStorage({
        "pid-0": {"tier": 0}, "pid-1": {"tier": 0},
        "pid-2": {"tier": 1}, "pid-3": {"tier": 1},
        "pid-4": {"tier": 2}, "pid-5": {"tier": 2},
    })
    embedder = FakeEmbedder()

    # Phase 1
    n1 = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
        priority_filter=_tier_le(1),
    )
    assert n1 == 4
    assert {pid for pid, _ in embedding_queue.peek_all()} == {"pid-4", "pid-5"}

    # Phase 2 (no filter)
    n2 = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
    )
    assert n2 == 2
    assert embedding_queue.peek_all() == []

    # Order: priority processed first — batch 0 contains only tier<=1 pids
    assert set(embedder.batches_embedded[0]) == {"pid-0", "pid-1", "pid-2", "pid-3"}
    assert set(embedder.batches_embedded[1]) == {"pid-4", "pid-5"}


@pytest.mark.asyncio
async def test_priority_drain_still_acks_missing_records(isolated_queue):
    """A queue entry whose Qdrant record has been deleted mustn't clog
    the queue just because the filter can't inspect a nonexistent payload."""
    for i in range(4):
        embedding_queue.append(f"pid-{i}", "source")
    # pid-1 and pid-3 have been deleted between queue-write and drain
    storage = FakeStorage({
        "pid-0": {"tier": 0},
        "pid-2": {"tier": 2},
    })
    embedder = FakeEmbedder()

    total = await drain_snapshot_queue(
        storage=storage, embedder=embedder, chunk_size=10, echo=lambda _: None,
        priority_filter=_tier_le(1),
    )

    assert total == 1  # only pid-0 embedded
    # pid-1 and pid-3 (missing from Qdrant) are cleared; pid-2 (tier=2,
    # exists but low priority) stays.
    remaining_pids = {pid for pid, _ in embedding_queue.peek_all()}
    assert remaining_pids == {"pid-2"}


@pytest.mark.asyncio
async def test_priority_drain_survives_mid_batch_crash(isolated_queue):
    """Crash-safety property from the base drain also holds under
    priority filtering — acked items are gone; the whole crashed chunk
    (both filter-passing AND filter-skipped items) stays in the queue."""
    for i in range(10):
        embedding_queue.append(f"pid-{i}", "source")
    storage = FakeStorage({
        # Chunk 1 (pid-0..4): all tier 0 → all embed, batch 0 succeeds.
        **{f"pid-{i}": {"tier": 0} for i in range(5)},
        # Chunk 2 (pid-5..9): 3 pass-filter items — enough to trigger the
        # embedder call, which raises via fail_on_batch=1.
        "pid-5": {"tier": 0}, "pid-6": {"tier": 2}, "pid-7": {"tier": 0},
        "pid-8": {"tier": 0}, "pid-9": {"tier": 2},
    })
    embedder = FakeEmbedder(fail_on_batch=1)  # crash on 2nd embed call

    with pytest.raises(RuntimeError):
        await drain_snapshot_queue(
            storage=storage, embedder=embedder, chunk_size=5, echo=lambda _: None,
            priority_filter=_tier_le(1),
        )

    remaining_pids = {pid for pid, _ in embedding_queue.peek_all()}
    # Chunk 1 (pid-0..4) processed & acked → gone.
    # Chunk 2 crashed before ack → ALL 5 items stay (filter-skipped tier-2
    # items included, since the crash preempted their ack too).
    assert remaining_pids == {f"pid-{i}" for i in range(5, 10)}
