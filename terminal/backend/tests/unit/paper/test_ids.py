"""Deterministic session ids: valid UUIDv7s, chronological, reproducible, collision-free."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from kterminal.core.ids import uuid7_time
from kterminal.paper.ids import RandomIds, SessionIds

T = datetime(2026, 1, 5, 14, 31, tzinfo=UTC)


def batch(ids: SessionIds, at: datetime, count: int) -> list[UUID]:
    ids.advance(at)
    return [ids() for _ in range(count)]


def test_session_ids_are_uuid7_carrying_the_batch_time() -> None:
    ids = SessionIds(0xABCDEF)
    for value in batch(ids, T, 5):
        assert value.version == 7
        assert value.variant == "specified in RFC 4122"
        assert uuid7_time(value) == T
        assert value.int & ((1 << 48) - 1) == 0xABCDEF


def test_session_ids_sort_in_creation_order_across_batches() -> None:
    ids = SessionIds(42)
    created = batch(ids, T, 20_000) + batch(ids, T + timedelta(minutes=1), 10)
    assert sorted(created) == created
    assert len(set(created)) == len(created)
    # the first 80 bits (used in client order ids) differ for every id of a batch
    assert len({value.hex[:20] for value in created}) == len(created)


def test_the_same_session_replays_the_same_ids() -> None:
    run = UUID("01999999-0000-7000-8000-123456789abc")
    first, second = SessionIds.for_run(run), SessionIds.for_run(run)
    assert batch(first, T, 3) == batch(second, T, 3)
    other = SessionIds.for_run(UUID("01999999-0000-7000-8000-cba987654321"))
    assert set(batch(other, T, 3)).isdisjoint(batch(SessionIds.for_run(run), T, 3))


def test_advancing_to_the_same_batch_continues_its_sequence() -> None:
    ids = SessionIds(1)
    head = batch(ids, T, 2)
    tail = batch(ids, T, 2)  # e.g. end-of-run records at the last batch's instant
    assert len(set(head + tail)) == 4
    assert sorted(head + tail) == head + tail


def test_session_ids_refuse_to_go_back_or_start_without_a_batch() -> None:
    ids = SessionIds(1)
    with pytest.raises(RuntimeError, match="advance"):
        ids()
    ids.advance(T)
    with pytest.raises(ValueError, match="back in time"):
        ids.advance(T - timedelta(minutes=1))


def test_random_ids_ignore_batches() -> None:
    ids = RandomIds()
    ids.advance(T)
    assert ids() != ids()
