"""The HTTP providers against fake venues that answer with each API's documented shapes."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kterminal.core.clock import Clock, SimulatedClock
from kterminal.core.errors import ClockError
from kterminal.marketdata.base import MarketDataError, MarketDataProvider
from kterminal.marketdata.providers import (
    BinanceSpotProvider,
    BinanceUsdmProvider,
    BybitLinearProvider,
    CoinbaseProvider,
    HttpProvider,
    HyperliquidProvider,
    OandaProvider,
    ProviderOptions,
)
from tests.fixtures.marketdata import (
    BinanceFake,
    BybitFake,
    Candle,
    CoinbaseFake,
    FakeTime,
    FakeVenue,
    HyperliquidFake,
    OandaFake,
    make_candles,
    network_error,
    status,
)

MINUTE = timedelta(minutes=1)
NOW = datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC)  # the 12:00 candle is still forming
FORMING = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TOKEN = "practice-token-123"


@dataclass(frozen=True)
class Case:
    id: str
    instrument: str
    symbol: str
    fake: Callable[[str, list[Candle], Clock], FakeVenue]
    provider: Callable[..., HttpProvider]
    window: int
    integer_volume: bool = False
    error_text: str = ""  # the venue's error message for an unknown symbol


def _oanda(**kwargs: Any) -> HttpProvider:
    return OandaProvider(token=SecretStr(TOKEN), **kwargs)


CASES = [
    Case("binance_usdm", "BTCUSD", "BTCUSDT", BinanceFake, BinanceUsdmProvider, 1500,
         error_text="Invalid symbol. (code -1121)"),
    Case("binance_spot", "PUMPUSD", "PUMPUSDT",
         lambda s, c, k: BinanceFake(s, c, k, path="/api/v3/klines", max_limit=1000),
         BinanceSpotProvider, 1000, error_text="Invalid symbol. (code -1121)"),
    Case("bybit_linear", "SOLUSD", "SOLUSDT", BybitFake, BybitLinearProvider, 1000,
         error_text="retCode 10001: params error: symbol invalid"),
    Case("coinbase", "ZECUSD", "ZEC-USD", CoinbaseFake, CoinbaseProvider, 299,
         error_text="NotFound"),
    Case("hyperliquid", "HYPEUSD", "HYPE", HyperliquidFake, HyperliquidProvider, 5000),
    Case("oanda", "XAUUSD", "XAU_USD", OandaFake, _oanda, 4999, integer_volume=True,
         error_text="Invalid value specified for 'instrument'"),
]  # fmt: skip
BY_ID = {case.id: case for case in CASES}


@dataclass
class Setup:
    provider: HttpProvider
    fake: FakeVenue
    clock: SimulatedClock
    time: FakeTime


def setup(
    case: Case,
    candles: list[Candle],
    *,
    now: datetime = NOW,
    loose: bool = False,
    options: ProviderOptions | None = None,
    symbol: str | None = None,
    **provider_kwargs: Any,
) -> Setup:
    clock = SimulatedClock(now)
    fake = case.fake(case.symbol, candles, clock)
    fake.loose = loose
    fake_time = FakeTime()
    provider = case.provider(
        symbols={case.instrument: symbol or case.symbol},
        clock=clock,
        transport=httpx.MockTransport(fake),
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
        options=options or ProviderOptions(),
        **provider_kwargs,
    )
    return Setup(provider, fake, clock, fake_time)


def candles_for(case: Case, minutes: int, **kwargs: Any) -> list[Candle]:
    """``minutes`` closed candles ending 11:59, plus the forming 12:00 one."""
    return make_candles(
        FORMING - minutes * MINUTE, FORMING, integer_volume=case.integer_volume, **kwargs
    )


def expected(case: Case, candles: list[Candle], start: datetime, end: datetime) -> list[Any]:
    return [
        c.bar(case.instrument, case.id) for c in candles if start <= c.t < end and c.t < FORMING
    ]


ids = pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])


# ── behaviour every provider shares ──────────────────────────────────────────
@ids
async def test_history_pages_through_windows_and_returns_closed_bars_oldest_first(
    case: Case,
) -> None:
    # Hyperliquid keeps only its latest 5,000 candles (the forming one included)
    minutes = 4999 if case.id == "hyperliquid" else 2 * case.window + 7
    candles = candles_for(case, minutes)
    s = setup(case, candles)
    start = FORMING - minutes * MINUTE
    bars = await s.provider.history(case.instrument, start, NOW + timedelta(hours=1))
    assert bars == expected(case, candles, start, FORMING)
    assert len(bars) == minutes
    assert all(b.open_time < a.open_time for a, b in zip(bars[1:], bars, strict=False))
    assert FORMING not in {b.open_time for b in bars}
    assert {b.source for b in bars} == {case.id}
    assert len(s.fake.requests) == math.ceil(minutes / case.window)
    assert isinstance(s.provider, MarketDataProvider)


@ids
async def test_missing_minutes_are_not_filled_in(case: Case) -> None:
    gap = {FORMING - 30 * MINUTE + i * MINUTE for i in range(5)}
    candles = make_candles(
        FORMING - 60 * MINUTE, FORMING, skip=frozenset(gap), integer_volume=case.integer_volume
    )
    s = setup(case, candles)
    bars = await s.provider.history(case.instrument, FORMING - 60 * MINUTE, FORMING)
    assert len(bars) == 55
    assert not gap & {b.open_time for b in bars}


@ids
async def test_candles_outside_the_request_and_the_forming_one_are_dropped(case: Case) -> None:
    candles = candles_for(case, 120)
    strict = setup(case, candles)
    loose = setup(case, candles, loose=True)  # the venue ignores the end bound
    start, end = FORMING - 100 * MINUTE, FORMING - 40 * MINUTE
    assert await loose.provider.history(
        case.instrument, start, end
    ) == await strict.provider.history(case.instrument, start, end)
    latest = await loose.provider.latest(case.instrument, FORMING - 10 * MINUTE)
    assert [b.open_time for b in latest] == [FORMING - i * MINUTE for i in range(10, 0, -1)]


@ids
async def test_latest_returns_closed_bars_since(case: Case) -> None:
    candles = candles_for(case, 30)
    s = setup(case, candles)
    bars = await s.provider.latest(case.instrument, FORMING - 10 * MINUTE)
    assert bars == expected(case, candles, FORMING - 10 * MINUTE, FORMING)
    assert len(s.fake.requests) == 1
    # one minute later the 12:00 bar has closed (plus the close delay) and is delivered
    s.clock.set(NOW + MINUTE)
    s.fake.candles.extend(make_candles(FORMING + MINUTE, FORMING + MINUTE))
    newer = await s.provider.latest(case.instrument, FORMING)
    assert [b.open_time for b in newer] == [FORMING]


@ids
async def test_a_bar_counts_as_closed_only_after_the_close_delay(case: Case) -> None:
    candles = candles_for(case, 5)
    s = setup(case, candles, now=FORMING + timedelta(seconds=1))  # 11:59 ended 1 s ago
    bars = await s.provider.latest(case.instrument, FORMING - 5 * MINUTE)
    assert bars[-1].open_time == FORMING - 2 * MINUTE
    s.clock.set(FORMING + timedelta(seconds=2))
    bars = await s.provider.latest(case.instrument, FORMING - 5 * MINUTE)
    assert bars[-1].open_time == FORMING - MINUTE


@ids
async def test_prices_and_volumes_are_exact_decimals(case: Case) -> None:
    candles = candles_for(case, 3, base="0.000012345678", step="0.000000001", volume="0.1")
    s = setup(case, candles)
    bars = await s.provider.history(case.instrument, FORMING - 3 * MINUTE, FORMING)
    for bar, candle in zip(bars, candles, strict=False):
        assert (str(bar.open), str(bar.high), str(bar.low), str(bar.close)) == (
            candle.o,
            candle.h,
            candle.low,
            candle.c,
        )
        assert bar.volume == Decimal(candle.v)


@ids
async def test_http_429_is_retried_after_retry_after(case: Case) -> None:
    candles = candles_for(case, 10)
    s = setup(case, candles)
    s.fake.script.append(status(429, {"msg": "Too many requests"}, headers={"Retry-After": "3"}))
    bars = await s.provider.history(case.instrument, FORMING - 10 * MINUTE, FORMING)
    assert len(bars) == 10
    assert s.time.sleeps == [3.0]
    assert len(s.fake.requests) == 2


@ids
async def test_server_and_network_errors_are_retried_with_exponential_backoff(
    case: Case,
) -> None:
    s = setup(case, candles_for(case, 10))
    s.fake.script.extend([status(503, "Service Unavailable"), network_error, status(502)])
    bars = await s.provider.history(case.instrument, FORMING - 10 * MINUTE, FORMING)
    assert len(bars) == 10
    assert s.time.sleeps == [0.5, 1.0, 2.0]


@ids
async def test_retries_give_up_with_a_clear_error(case: Case) -> None:
    s = setup(case, candles_for(case, 10), options=ProviderOptions(max_retries=2))
    s.fake.script.extend([status(500, "boom")] * 3)
    with pytest.raises(MarketDataError, match=r"HTTP 500: boom \(gave up after 3 attempts\)"):
        await s.provider.history(case.instrument, FORMING - 10 * MINUTE, FORMING)
    assert s.time.sleeps == [0.5, 1.0]


@ids
async def test_a_very_long_retry_after_fails_instead_of_waiting(case: Case) -> None:
    s = setup(case, candles_for(case, 10))
    s.fake.script.append(status(429, headers={"Retry-After": "3600"}))
    with pytest.raises(MarketDataError, match="asks to wait 3600 s"):
        await s.provider.history(case.instrument, FORMING - 10 * MINUTE, FORMING)
    assert s.time.sleeps == []


@pytest.mark.parametrize("case", [c for c in CASES if c.error_text], ids=lambda c: c.id)
async def test_venue_errors_fail_at_once_with_the_venue_message(case: Case) -> None:
    s = setup(case, candles_for(case, 10), symbol="NOPE-NOPE" if case.id == "coinbase" else "NOPE")
    with pytest.raises(MarketDataError) as caught:
        await s.provider.history(case.instrument, FORMING - 10 * MINUTE, FORMING)
    assert case.error_text in str(caught.value)
    assert str(caught.value).startswith(case.id)
    assert len(s.fake.requests) == 1  # not retried


@ids
async def test_arguments_are_checked(case: Case) -> None:
    s = setup(case, candles_for(case, 10))
    with pytest.raises(MarketDataError, match="does not serve ETHUSD"):
        await s.provider.history("ETHUSD", FORMING - 10 * MINUTE, FORMING)
    with pytest.raises(ClockError):
        await s.provider.history(case.instrument, datetime(2026, 10, 9), FORMING)  # noqa: DTZ001
    assert await s.provider.history(case.instrument, FORMING, FORMING - MINUTE) == []
    assert await s.provider.history(case.instrument, NOW + MINUTE, NOW + 9 * MINUTE) == []
    assert s.fake.requests == []
    # a start inside a minute begins at the next whole minute
    start = FORMING - timedelta(minutes=3, seconds=10)
    bars = await s.provider.history(case.instrument, start, FORMING)
    assert [b.open_time for b in bars] == [FORMING - i * MINUTE for i in (3, 2, 1)]
    assert s.provider.supports(case.instrument)
    assert not s.provider.supports("ETHUSD")
    await s.provider.aclose()
    await s.provider.aclose()  # idempotent
