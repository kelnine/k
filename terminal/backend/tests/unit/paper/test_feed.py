"""The live feed: one closed minute at a time, never out of order, never stuck on one
instrument (fake provider, fake clock)."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from kterminal.paper.feed import FeedConfig, LiveFeed
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.forward import FakeProvider, FakeTime, market_bars

# Monday 5 January 2026, 21:50 UTC: spot gold closes at 22:00 UTC (17:00 New York) for its
# daily break and reopens at 23:00 UTC; NEAR trades around the clock.
T = datetime(2026, 1, 5, 21, 50, tzinfo=UTC)
MIN = timedelta(minutes=1)
METALS = lab_catalog().sessions.calendar("metals_otc")
CRYPTO = lab_catalog().sessions.calendar("crypto_24x7")


def setup(
    start: datetime = T, *, now: datetime | None = None, config: FeedConfig | None = None
) -> tuple[LiveFeed, FakeTime, FakeProvider, FakeProvider]:
    clock = FakeTime(now or start)
    gold = FakeProvider(
        "fake-fx",
        market_bars(
            "XAUUSD",
            start=start - 30 * MIN,
            minutes=200,
            price="4000.00",
            tick="0.01",
            seed=1,
            is_open=METALS.is_open,
            source="fake-fx",
        ),
        clock,
    )
    near = FakeProvider(
        "fake-crypto",
        market_bars(
            "NEARUSD",
            start=start - 30 * MIN,
            minutes=200,
            price="3.000",
            tick="0.001",
            seed=2,
            source="fake-crypto",
        ),
        clock,
    )
    feed = LiveFeed(
        ["NEARUSD", "XAUUSD"],
        {"XAUUSD": gold, "NEARUSD": near},
        {"XAUUSD": METALS, "NEARUSD": CRYPTO},
        start=start,
        clock=clock,
        wait=clock.wait,
        config=config,
    )
    return feed, clock, gold, near


async def test_a_minute_is_handed_out_once_every_open_instrument_delivered_it() -> None:
    feed, clock, _, _ = setup()
    batch = await feed.next_batch()
    assert batch is not None
    assert batch.minute == T and batch.close_time == T + MIN
    assert [(b.instrument, b.open_time) for b in batch.bars] == [("NEARUSD", T), ("XAUUSD", T)]
    assert batch.missing == () and batch.late == ()
    assert clock.now() == T + MIN + timedelta(seconds=2)  # poll delay, no waiting beyond it
    second = await feed.next_batch()
    assert second is not None and second.minute == T + MIN
    status = feed.status()
    assert status["XAUUSD"]["state"] == "ok"
    assert status["XAUUSD"]["provider"] == "fake-fx"
    assert status["XAUUSD"]["last_bar_open"] == (T + MIN).isoformat()
    assert status["XAUUSD"]["lag_seconds"] == 2.0


async def test_a_missing_instrument_is_not_waited_for_past_the_timeout_and_its_late_bar_is_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed, clock, gold, _ = setup()
    gold.hold("XAUUSD", T, until=T + 2 * MIN + timedelta(seconds=1))  # 61 s late
    batch = await feed.next_batch()
    assert batch is not None
    assert [b.instrument for b in batch.bars] == ["NEARUSD"]
    assert batch.missing == ("XAUUSD",)
    assert clock.now() == T + MIN + timedelta(seconds=20)  # the batch timeout
    assert feed.status()["XAUUSD"]["state"] == "stale"

    following = await feed.next_batch()
    assert following is not None
    assert [b.instrument for b in following.bars] == ["NEARUSD", "XAUUSD"]
    assert [(b.instrument, b.open_time) for b in following.late] == [("XAUUSD", T)]
    assert "paper.feed.late_bar_dropped" in caplog.text
    assert feed.status()["XAUUSD"]["state"] == "ok"


async def test_a_failing_provider_backs_off_and_the_others_carry_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed, clock, _, near = setup()
    near.failures["NEARUSD"] = 2
    caplog.set_level(logging.WARNING)
    batch = await feed.next_batch()
    assert batch is not None
    assert [b.instrument for b in batch.bars] == ["XAUUSD"]
    assert batch.missing == ()  # backing off: not waited for
    assert clock.now() == T + MIN + timedelta(seconds=2)
    status = feed.status()["NEARUSD"]
    assert status["state"] == "stale"
    assert "HTTP 503" in str(status["last_error"])
    assert "paper.feed.provider_error" in caplog.text

    second = await feed.next_batch()  # retried after 5 s: fails again (back-off 10 s)
    assert second is not None and [b.instrument for b in second.bars] == ["XAUUSD"]
    third = await feed.next_batch()  # recovers; earlier minutes arrive too late
    assert third is not None
    assert [b.instrument for b in third.bars] == ["NEARUSD", "XAUUSD"]
    assert {b.open_time for b in third.late} == {T, T + MIN}
    assert feed.status()["NEARUSD"] == {
        "provider": "fake-crypto",
        "last_bar_open": (T + 2 * MIN).isoformat(),
        "lag_seconds": 2.0,
        "state": "ok",
        "last_error": None,
    }


async def test_instruments_in_a_market_closure_are_not_waited_for() -> None:
    feed, clock, gold, _ = setup()
    batches = []
    while feed.cursor < T + 15 * MIN:
        batch = await feed.next_batch()
        assert batch is not None
        batches.append(batch)
    closed = [b for b in batches if b.minute >= datetime(2026, 1, 5, 22, 0, tzinfo=UTC)]
    assert closed and all([x.instrument for x in b.bars] == ["NEARUSD"] for b in closed)
    assert all(b.missing == () for b in batches)
    assert clock.now() == T + 15 * MIN + timedelta(seconds=2)  # never waited for gold
    assert feed.status()["XAUUSD"]["state"] == "closed"
    assert not [c for c in gold.calls if c[2] >= datetime(2026, 1, 5, 22, 1, tzinfo=UTC)]


async def test_after_a_restart_the_feed_catches_up_in_order_without_waiting() -> None:
    feed, clock, gold, near = setup(T - 20 * MIN, now=T + timedelta(seconds=30))
    gold.page = near.page = 7  # the venue pages its answers
    minutes = []
    while feed.cursor < T:
        batch = await feed.next_batch()
        assert batch is not None
        assert batch.missing == () and batch.late == ()
        assert [b.instrument for b in batch.bars] == ["NEARUSD", "XAUUSD"]
        minutes.append(batch.minute)
    assert minutes == [T - 20 * MIN + i * MIN for i in range(20)]
    assert clock.now() == T + timedelta(seconds=30)  # no time passed: all deadlines were past


async def test_a_later_bar_proves_a_gap_at_the_venue() -> None:
    feed, clock, gold, _ = setup(T - 10 * MIN, now=T)
    gold.bars["XAUUSD"] = [b for b in gold.bars["XAUUSD"] if b.open_time != T - 8 * MIN]
    batches = []
    for _ in range(4):
        batch = await feed.next_batch()
        assert batch is not None
        batches.append(batch)
    gap = batches[2]
    assert gap.minute == T - 8 * MIN
    assert [b.instrument for b in gap.bars] == ["NEARUSD"]
    assert gap.missing == ()
    assert clock.now() == T


async def test_the_feed_stops_when_asked() -> None:
    feed, clock, _, _ = setup()
    clock.stop_at = T + timedelta(seconds=30)
    assert await feed.next_batch() is None
    assert feed.cursor == T  # nothing was handed out


def test_the_feed_starts_on_a_minute() -> None:
    clock = FakeTime(T)
    with pytest.raises(ValueError, match="minute"):
        LiveFeed([], {}, {}, start=T + timedelta(seconds=5), clock=clock, wait=clock.wait)


async def test_an_instrument_without_a_provider_is_reported_and_ignored() -> None:
    clock = FakeTime(T)
    feed = LiveFeed(["MNQ"], {}, {}, start=T, clock=clock, wait=clock.wait)
    batch = await feed.next_batch()
    assert batch is not None and batch.bars == () and batch.missing == ()
    assert feed.status()["MNQ"]["state"] == "no_provider"
