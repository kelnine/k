"""Venue-specific behaviour: exact request parameters at window boundaries, error codes,
rate-limit signals, authentication and documented example payloads."""

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kterminal.config.settings import OandaEnvironment
from kterminal.core.clock import SimulatedClock
from kterminal.marketdata.base import MarketDataError
from kterminal.marketdata.providers import (
    OANDA_HOSTS,
    BinanceSpotProvider,
    BinanceUsdmProvider,
    BybitLinearProvider,
    CoinbaseProvider,
    HyperliquidProvider,
    OandaProvider,
    ProviderOptions,
)
from kterminal.marketdata.providers._http import HttpProvider
from tests.fixtures.marketdata import (
    BinanceFake,
    BybitFake,
    CoinbaseFake,
    FakeTime,
    HyperliquidFake,
    OandaFake,
    make_candles,
    status,
)

MINUTE = timedelta(minutes=1)
NOW = datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC)
FORMING = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TOKEN = "practice-token-123"


def ms(ts: datetime) -> int:
    return int(ts.timestamp()) * 1000


def provider(
    cls: type[HttpProvider],
    handler: Any,
    symbols: dict[str, str],
    *,
    fake_time: FakeTime | None = None,
    now: datetime = NOW,
    **kwargs: Any,
) -> HttpProvider:
    fake_time = fake_time or FakeTime()
    return cls(
        symbols,
        clock=SimulatedClock(now),
        transport=httpx.MockTransport(handler),
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
        **kwargs,
    )


def oanda(handler: Any, **kwargs: Any) -> HttpProvider:
    return provider(OandaProvider, handler, {"XAUUSD": "XAU_USD"}, token=SecretStr(TOKEN), **kwargs)


# ── Binance ──────────────────────────────────────────────────────────────────
async def test_binance_usdm_requests_1500_minute_windows_ending_at_the_close_time() -> None:
    start = FORMING - 3200 * MINUTE
    fake = BinanceFake("BTCUSDT", make_candles(start, FORMING), SimulatedClock(NOW))
    p = provider(BinanceUsdmProvider, fake, {"BTCUSD": "BTCUSDT"})
    bars = await p.history("BTCUSD", start, FORMING)
    assert len(bars) == 3200
    params = [dict(r.url.params) for r in fake.requests]
    assert [r.url.host for r in fake.requests] == ["fapi.binance.com"] * 3
    assert params[0] == {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "startTime": str(ms(start)),
        "endTime": str(ms(start + 1499 * MINUTE) + 59_999),
        "limit": "1500",
    }
    assert params[1]["startTime"] == str(ms(start + 1500 * MINUTE))
    assert params[2]["startTime"] == str(ms(start + 3000 * MINUTE))
    assert params[2]["endTime"] == str(ms(FORMING - MINUTE) + 59_999)


async def test_binance_spot_uses_the_spot_endpoint_and_1000_row_windows() -> None:
    start = FORMING - 1001 * MINUTE
    fake = BinanceFake(
        "PUMPUSDT", make_candles(start, FORMING), SimulatedClock(NOW), path="/api/v3/klines",
        max_limit=1000,
    )  # fmt: skip
    p = provider(BinanceSpotProvider, fake, {"PUMPUSD": "PUMPUSDT"})
    assert len(await p.history("PUMPUSD", start, FORMING)) == 1001
    assert [r.url.host for r in fake.requests] == ["api.binance.com"] * 2
    assert [r.url.params["limit"] for r in fake.requests] == ["1000", "1000"]


async def test_binance_451_is_a_geo_restriction_and_is_not_retried() -> None:
    body = {
        "code": 0,
        "msg": "Service unavailable from a restricted location according to 'b. Eligibility' "
        "in https://www.binance.com/en/terms.",
    }
    fake_time = FakeTime()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return status(451, body)

    p = provider(BinanceUsdmProvider, handler, {"BTCUSD": "BTCUSDT"}, fake_time=fake_time)
    with pytest.raises(MarketDataError) as caught:
        await p.history("BTCUSD", FORMING - 10 * MINUTE, FORMING)
    message = str(caught.value)
    assert "HTTP 451" in message
    assert "restricted location" in message
    assert "KT_MARKETDATA__DISABLED_PROVIDERS=binance_usdm" in message
    assert len(calls) == 1
    assert fake_time.sleeps == []


@pytest.mark.parametrize(("code", "hint"), [(418, "banned"), (403, "web application firewall")])
async def test_binance_bans_and_waf_blocks_fail_at_once(code: int, hint: str) -> None:
    p = provider(
        BinanceUsdmProvider, lambda r: status(code, "", headers={"Retry-After": "120"}),
        {"BTCUSD": "BTCUSDT"},
    )  # fmt: skip
    with pytest.raises(MarketDataError, match=hint):
        await p.history("BTCUSD", FORMING - 10 * MINUTE, FORMING)


async def test_binance_pauses_until_the_next_minute_near_the_weight_limit() -> None:
    start = FORMING - 3000 * MINUTE
    fake = BinanceFake("BTCUSDT", make_candles(start, FORMING), SimulatedClock(NOW))
    fake.used_weight = 2200  # ≥ 90 % of 2,400
    fake_time = FakeTime()
    p = provider(BinanceUsdmProvider, fake, {"BTCUSD": "BTCUSDT"}, fake_time=fake_time)
    await p.history("BTCUSD", start, FORMING)
    assert fake_time.sleeps == [31.0]  # NOW is hh:mm:30 → wait to the next minute (+1 s)


async def test_binance_rejects_a_kline_that_is_not_one_minute_long() -> None:
    # the documented example row (a 1-week kline): its close time is not open + 59 999 ms
    row = [1499040000000, "0.01634790", "0.80000000", "0.01575800", "0.01577100",
           "148976.11427815", 1499644799999, "2434.19055334", 308, "1756.87402397",
           "28.46694368", "0"]  # fmt: skip
    p = provider(BinanceUsdmProvider, lambda r: status(200, [row]), {"BTCUSD": "BTCUSDT"})
    with pytest.raises(MarketDataError, match="not a 1-minute kline"):
        await p.history("BTCUSD", FORMING - 10 * MINUTE, FORMING)


async def test_binance_documented_example_shape_parses() -> None:
    # The documented kline row, re-timed to a 1-minute kline: 12 fields, prices and
    # volumes as strings, trade count as a number, close time = open time + 59 999 ms
    t = ms(FORMING - MINUTE)
    row = [t, "0.01634790", "0.80000000", "0.01575800", "0.01577100", "148976.11427815",
           t + 59_999, "2434.19055334", 308, "1756.87402397", "28.46694368", "0"]  # fmt: skip
    p = provider(BinanceUsdmProvider, lambda r: status(200, [row]), {"BTCUSD": "BTCUSDT"})
    (bar,) = await p.history("BTCUSD", FORMING - 5 * MINUTE, FORMING)
    assert (bar.open_time, bar.close_time) == (FORMING - MINUTE, FORMING)
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        Decimal("0.01634790"),
        Decimal("0.80000000"),
        Decimal("0.01575800"),
        Decimal("0.01577100"),
        Decimal("148976.11427815"),
    )
    assert str(bar.open) == "0.01634790"  # the venue's text, trailing zeros included
    assert (bar.instrument, bar.source) == ("BTCUSD", "binance_usdm")


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        ([1, "1", "1", "1", "1"], "at least 7 fields"),
        ([1_700_000_000_000, "1", "1", "1", "1", "1", 1_700_000_059_999], "not on a whole minute"),
        ([1_699_999_980_000, "x", "1", "1", "1", "1", 1_700_000_039_999], "open must be a number"),
        ([1_699_999_980_000, True, "2", "1", "1", "1", 1_700_000_039_999], "open must be a number"),
        ([1_699_999_980_000, "1", "0.5", "1", "1", "1", 1_700_000_039_999], "inconsistent OHLC"),
        ([1_699_999_980_000, "1", "1", "1", "1", "-1", 1_700_000_039_999], "negative"),
        ("not a row", "expected a list"),
    ],
)
async def test_binance_payloads_are_parsed_strictly(row: Any, problem: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return status(200, [row])

    p = provider(
        BinanceUsdmProvider, handler, {"BTCUSD": "BTCUSDT"}, now=datetime(2023, 11, 15, tzinfo=UTC)
    )
    with pytest.raises(MarketDataError, match=problem):
        await p.history(
            "BTCUSD", datetime(2023, 11, 14, tzinfo=UTC), datetime(2023, 11, 15, tzinfo=UTC)
        )


async def test_duplicate_minutes_in_one_response_must_agree() -> None:
    t = ms(FORMING - 2 * MINUTE)
    row = [t, "1", "2", "0.5", "1.5", "3", t + 59_999, "0", 1, "0", "0", "0"]
    same = provider(BinanceUsdmProvider, lambda r: status(200, [row, row]), {"BTCUSD": "BTCUSDT"})
    assert len(await same.history("BTCUSD", FORMING - 5 * MINUTE, FORMING)) == 1
    other = [*row[:4], "1.6", *row[5:]]
    different = provider(
        BinanceUsdmProvider, lambda r: status(200, [row, other]), {"BTCUSD": "BTCUSDT"}
    )
    with pytest.raises(MarketDataError, match="two different BTCUSD bars"):
        await different.history("BTCUSD", FORMING - 5 * MINUTE, FORMING)


# ── Bybit ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("end_exclusive", [False, True])
async def test_bybit_windows_are_complete_and_newest_first_is_sorted(end_exclusive: bool) -> None:
    start = FORMING - 1500 * MINUTE
    fake = BybitFake("SOLUSDT", make_candles(start, FORMING), SimulatedClock(NOW))
    fake.end_exclusive = end_exclusive
    p = provider(BybitLinearProvider, fake, {"SOLUSD": "SOLUSDT"})
    bars = await p.history("SOLUSD", start, FORMING)
    assert [b.open_time for b in bars] == [start + i * MINUTE for i in range(1500)]
    first, second = (dict(r.url.params) for r in fake.requests)
    assert first == {
        "category": "linear",
        "symbol": "SOLUSDT",
        "interval": "1",
        "start": str(ms(start)),
        "end": str(ms(start + 999 * MINUTE) + 59_999),
        "limit": "1000",
    }
    assert second["start"] == str(ms(start + 1000 * MINUTE))
    assert second["end"] == str(ms(FORMING - MINUTE) + 59_999)


async def test_bybit_rate_limit_ret_code_is_retried() -> None:
    fake = BybitFake("SOLUSDT", make_candles(FORMING - 5 * MINUTE, FORMING), SimulatedClock(NOW))
    fake.script.append(
        status(200, {"retCode": 10006, "retMsg": "Too many visits!", "result": {}, "time": 1})
    )
    fake_time = FakeTime()
    p = provider(BybitLinearProvider, fake, {"SOLUSD": "SOLUSDT"}, fake_time=fake_time)
    assert len(await p.history("SOLUSD", FORMING - 5 * MINUTE, FORMING)) == 5
    assert fake_time.sleeps == [0.5]


async def test_bybit_403_explains_bans_and_blocked_countries() -> None:
    page = "<html><body><h1>403 ERROR</h1> The request could not be satisfied. </body></html>"
    p = provider(BybitLinearProvider, lambda r: status(403, page), {"SOLUSD": "SOLUSDT"})
    with pytest.raises(
        MarketDataError, match=r"HTTP 403: <html>.*blocked country \(e\.g\. the US\)"
    ):
        await p.history("SOLUSD", FORMING - 5 * MINUTE, FORMING)


@pytest.mark.parametrize(
    ("payload", "problem"),
    [
        ({"retMsg": "OK"}, "without retCode"),
        ({"retCode": 0, "result": {"symbol": "BTCUSDT", "list": []}}, "not 'SOLUSDT'"),
        ({"retCode": 0, "result": {"category": "inverse", "list": []}}, "category 'inverse'"),
        ({"retCode": 0, "result": {"list": [["1", "2"]]}}, "at least 6 fields"),
        ({"retCode": 0, "result": None}, "result: expected an object"),
    ],
)
async def test_bybit_payloads_are_parsed_strictly(payload: Any, problem: str) -> None:
    p = provider(BybitLinearProvider, lambda r: status(200, payload), {"SOLUSD": "SOLUSDT"})
    with pytest.raises(MarketDataError, match=problem):
        await p.history("SOLUSD", FORMING - 5 * MINUTE, FORMING)


async def test_bybit_documented_example_shape_parses() -> None:
    # The v5 docs' example, re-timed to 1-minute candles of a linear symbol
    t0 = ms(FORMING - 3 * MINUTE)
    body = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "symbol": "SOLUSDT",
            "category": "linear",
            "list": [
                [str(t0 + 120_000), "17071", "17073", "17027", "17055.5", "268611", "15.74462667"],
                [str(t0 + 60_000), "17071.5", "17071.5", "17061", "17071", "4177", "0.24469757"],
                [str(t0), "17086.5", "17088", "16978", "17071.5", "6356", "0.37288112"],
            ],
        },
        "retExtInfo": {},
        "time": 1672025956592,
    }
    p = provider(BybitLinearProvider, lambda r: status(200, body), {"SOLUSD": "SOLUSDT"})
    bars = await p.history("SOLUSD", FORMING - 3 * MINUTE, FORMING)
    assert [(b.open, b.high, b.low, b.close, b.volume) for b in bars] == [
        (Decimal("17086.5"), Decimal("17088"), Decimal("16978"), Decimal("17071.5"), Decimal(6356)),
        (Decimal("17071.5"), Decimal("17071.5"), Decimal("17061"), Decimal("17071"), Decimal(4177)),
        (Decimal("17071"), Decimal("17073"), Decimal("17027"), Decimal("17055.5"), Decimal(268611)),
    ]


# ── Coinbase ─────────────────────────────────────────────────────────────────
async def test_coinbase_windows_stay_within_300_buckets() -> None:
    start = FORMING - 650 * MINUTE
    fake = CoinbaseFake("ZEC-USD", make_candles(start, FORMING), SimulatedClock(NOW))
    p = provider(CoinbaseProvider, fake, {"ZECUSD": "ZEC-USD"})
    assert len(await p.history("ZECUSD", start, FORMING)) == 650
    params = [dict(r.url.params) for r in fake.requests]
    assert [r.url.path for r in fake.requests] == ["/products/ZEC-USD/candles"] * 3
    assert params[0] == {
        "granularity": "60",
        "start": (start).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": (start + 299 * MINUTE).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    assert params[1]["start"] == (start + 299 * MINUTE).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert params[2]["end"] == FORMING.strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_coinbase_documented_example_reads_low_high_open_close() -> None:
    # The candle layout from the Exchange API docs: [time, low, high, open, close, volume]
    t = int((FORMING - 3 * MINUTE).timestamp())
    text = (
        f"[[{t + 120},0.02505,0.02508,0.02506,0.02507,0.02816506],"
        f"[{t + 60},0.02505,0.02507,0.02505,0.02507,1.63830323],"
        f"[{t},0.02505,0.02507,0.02505,0.02507,0.19918178]]"
    )
    p = provider(CoinbaseProvider, lambda r: httpx.Response(200, text=text), {"ZECUSD": "ZEC-USD"})
    bars = await p.history("ZECUSD", FORMING - 3 * MINUTE, FORMING)
    last = bars[-1]
    assert (last.open, last.high, last.low, last.close, last.volume) == (
        Decimal("0.02506"),
        Decimal("0.02508"),
        Decimal("0.02505"),
        Decimal("0.02507"),
        Decimal("0.02816506"),
    )
    assert str(bars[0].volume) == "0.19918178"  # no float round-trip


async def test_coinbase_json_nan_is_rejected() -> None:
    t = int((FORMING - MINUTE).timestamp())
    p = provider(
        CoinbaseProvider, lambda r: httpx.Response(200, text=f"[[{t},NaN,1,1,1,1]]"),
        {"ZECUSD": "ZEC-USD"},
    )  # fmt: skip
    with pytest.raises(MarketDataError, match="not valid JSON"):
        await p.history("ZECUSD", FORMING - 5 * MINUTE, FORMING)


# ── Hyperliquid ──────────────────────────────────────────────────────────────
async def test_hyperliquid_posts_a_candle_snapshot_request() -> None:
    fake = HyperliquidFake(
        "HYPE", make_candles(FORMING - 30 * MINUTE, FORMING), SimulatedClock(NOW)
    )
    p = provider(HyperliquidProvider, fake, {"HYPEUSD": "HYPE"})
    await p.history("HYPEUSD", FORMING - 30 * MINUTE, FORMING)
    (request,) = fake.requests
    assert (request.method, request.url.host, request.url.path) == (
        "POST",
        "api.hyperliquid.xyz",
        "/info",
    )
    assert json.loads(request.content) == {
        "type": "candleSnapshot",
        "req": {
            "coin": "HYPE",
            "interval": "1m",
            "startTime": ms(FORMING - 30 * MINUTE),
            "endTime": ms(FORMING - MINUTE) + 59_999,
        },
    }


async def test_hyperliquid_history_is_cut_to_the_available_depth(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = HyperliquidFake(
        "HYPE", make_candles(FORMING - 9000 * MINUTE, FORMING), SimulatedClock(NOW)
    )
    p = provider(HyperliquidProvider, fake, {"HYPEUSD": "HYPE"})
    with caplog.at_level(logging.WARNING):
        bars = await p.history("HYPEUSD", FORMING - 9000 * MINUTE, FORMING)
    assert len(bars) == 4999
    assert len(fake.requests) == 1
    assert "marketdata.history_truncated" in caplog.text
    assert json.loads(fake.requests[0].content)["req"]["startTime"] == ms(FORMING - 5000 * MINUTE)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"i": "15m"}, "interval '15m'"),
        ({"s": "ETH"}, "coin 'ETH'"),
        ({"T": 1}, "close time 1"),
        ({"o": None}, "o must be a number"),
    ],
)
async def test_hyperliquid_payloads_are_parsed_strictly(
    change: dict[str, Any], problem: str
) -> None:
    t = ms(FORMING - MINUTE)
    candle = {"t": t, "T": t + 59_999, "s": "HYPE", "i": "1m", "o": "2247.9", "c": "2226.4",
              "h": "2247.9", "l": "2224.6", "v": "591.6427", "n": 46}  # fmt: skip
    p = provider(
        HyperliquidProvider, lambda r: status(200, [{**candle, **change}]), {"HYPEUSD": "HYPE"}
    )
    with pytest.raises(MarketDataError, match=problem):
        await p.history("HYPEUSD", FORMING - 5 * MINUTE, FORMING)


async def test_hyperliquid_documented_example_shape_parses() -> None:
    # The candleSnapshot example from the info API docs, re-timed, with the forming candle
    t = ms(FORMING - MINUTE)
    rows = [
        {"t": t, "T": t + 59_999, "s": "HYPE", "i": "1m", "o": "2247.9", "c": "2226.4",
         "h": "2247.9", "l": "2224.6", "v": "591.6427", "n": 46},
        {"t": t + 60_000, "T": t + 119_999, "s": "HYPE", "i": "1m", "o": "2226.4",
         "c": "2230.0", "h": "2231.1", "l": "2226.4", "v": "12.5", "n": 3},
    ]  # fmt: skip
    p = provider(HyperliquidProvider, lambda r: status(200, rows), {"HYPEUSD": "HYPE"})
    (bar,) = await p.history("HYPEUSD", FORMING - 5 * MINUTE, NOW + MINUTE)  # forming dropped
    assert bar.open_time == FORMING - MINUTE
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        Decimal("2247.9"),
        Decimal("2247.9"),
        Decimal("2224.6"),
        Decimal("2226.4"),
        Decimal("591.6427"),
    )
    assert bar.source == "hyperliquid"


async def test_hyperliquid_422_fails_with_the_body_text() -> None:
    p = provider(
        HyperliquidProvider,
        lambda r: status(422, "Failed to deserialize the JSON body into the target type"),
        {"HYPEUSD": "HYPE"},
    )
    with pytest.raises(MarketDataError, match="HTTP 422: Failed to deserialize"):
        await p.history("HYPEUSD", FORMING - 5 * MINUTE, FORMING)


# ── OANDA ────────────────────────────────────────────────────────────────────
async def test_oanda_sends_the_token_and_asks_for_mid_m1_candles() -> None:
    start = FORMING - 6000 * MINUTE
    fake = OandaFake(
        "XAU_USD", make_candles(start, FORMING, integer_volume=True), SimulatedClock(NOW)
    )
    p = oanda(fake)
    bars = await p.history("XAUUSD", start, FORMING)
    assert len(bars) == 6000
    first, second = fake.requests
    assert first.url.host == "api-fxpractice.oanda.com"
    assert first.headers["authorization"] == f"Bearer {TOKEN}"
    assert first.headers["accept-datetime-format"] == "RFC3339"
    assert dict(first.url.params) == {
        "price": "M",
        "granularity": "M1",
        "from": start.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "to": (start + 4999 * MINUTE).strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
    }
    assert second.url.params["to"] == FORMING.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    assert bars[0].volume == Decimal(1)  # tick count, an integer


async def test_oanda_documented_example_shape_parses() -> None:
    # The v20 candles example (price=M), re-timed; the last candle is still forming
    def at(minutes: int) -> str:
        return (FORMING - minutes * MINUTE).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")

    body = {
        "instrument": "XAU_USD",
        "granularity": "M1",
        "candles": [
            {"complete": True, "volume": 52, "time": at(2),
             "mid": {"o": "1.09886", "h": "1.09889", "l": "1.09880", "c": "1.09883"}},
            {"complete": True, "volume": 7, "time": at(1),
             "mid": {"o": "1.09883", "h": "1.09885", "l": "1.09878", "c": "1.09878"}},
            {"complete": False, "volume": 3, "time": at(0),
             "mid": {"o": "1.09878", "h": "1.09880", "l": "1.09877", "c": "1.09879"}},
        ],
    }  # fmt: skip
    p = oanda(lambda r: status(200, body))
    bars = await p.history("XAUUSD", FORMING - 5 * MINUTE, FORMING)
    assert [b.open_time for b in bars] == [FORMING - 2 * MINUTE, FORMING - MINUTE]
    first = bars[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        Decimal("1.09886"),
        Decimal("1.09889"),
        Decimal("1.09880"),
        Decimal("1.09883"),
        Decimal(52),
    )
    assert (first.instrument, first.source) == ("XAUUSD", "oanda")


def test_oanda_hosts_and_token_requirement() -> None:
    assert OANDA_HOSTS[OandaEnvironment.PRACTICE] == "https://api-fxpractice.oanda.com"
    assert OANDA_HOSTS[OandaEnvironment.LIVE] == "https://api-fxtrade.oanda.com"
    with pytest.raises(ValueError, match="token"):
        OandaProvider({"XAUUSD": "XAU_USD"}, token=SecretStr("  "))


async def test_oanda_live_environment_uses_the_live_host() -> None:
    fake = OandaFake(
        "XAU_USD",
        make_candles(FORMING - 5 * MINUTE, FORMING, integer_volume=True),
        SimulatedClock(NOW),
    )
    p = oanda(fake, environment=OandaEnvironment.LIVE)
    await p.history("XAUUSD", FORMING - 5 * MINUTE, FORMING)
    assert fake.requests[0].url.host == "api-fxtrade.oanda.com"


async def test_oanda_drops_candles_it_still_marks_incomplete() -> None:
    clock = SimulatedClock(NOW)
    venue_clock = SimulatedClock(FORMING - timedelta(seconds=10))  # the venue is 40 s behind
    fake = OandaFake(
        "XAU_USD", make_candles(FORMING - 5 * MINUTE, FORMING, integer_volume=True), clock,
        venue_clock=venue_clock,
    )  # fmt: skip
    p = oanda(fake)
    bars = await p.latest("XAUUSD", FORMING - 5 * MINUTE)
    assert bars[-1].open_time == FORMING - 2 * MINUTE  # 11:59 is not complete at the venue yet
    venue_clock.set(NOW)
    bars = await p.latest("XAUUSD", FORMING - 5 * MINUTE)
    assert bars[-1].open_time == FORMING - MINUTE


async def test_oanda_rejected_token_never_leaks(caplog: pytest.LogCaptureFixture) -> None:
    fake = OandaFake("XAU_USD", [], SimulatedClock(NOW), token="another-token")
    fake.script.extend([status(429, {"errorMessage": "rate"}), status(503)])
    p = oanda(fake)
    with caplog.at_level(logging.DEBUG), pytest.raises(MarketDataError) as caught:
        await p.history("XAUUSD", FORMING - 5 * MINUTE, FORMING)
    message = str(caught.value)
    assert "HTTP 401" in message
    assert "Insufficient authorization" in message
    assert "KT_MARKETDATA__OANDA_ENVIRONMENT=practice" in message
    assert TOKEN not in message
    assert TOKEN not in caplog.text
    assert "marketdata.retry" in caplog.text
    assert TOKEN not in repr(p.__dict__)


@pytest.mark.parametrize(
    ("time", "problem"),
    [
        ("2026-10-09T11:59:00.000000001Z", "not on a whole minute"),
        ("2026-10-09T11:59:30.000000000Z", "not on a whole minute"),
        ("1696118400.000000000", "RFC 3339"),
        (None, "RFC 3339"),
    ],
)
async def test_oanda_times_are_parsed_strictly(time: Any, problem: str) -> None:
    body = {
        "instrument": "XAU_USD",
        "granularity": "M1",
        "candles": [
            {"complete": True, "volume": 5, "time": time,
             "mid": {"o": "1", "h": "1", "l": "1", "c": "1"}}
        ],
    }  # fmt: skip
    p = oanda(lambda r: status(200, body))
    with pytest.raises(MarketDataError, match=problem):
        await p.history("XAUUSD", FORMING - 5 * MINUTE, FORMING)


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ({"instrument": "EUR_USD", "candles": []}, "not 'XAU_USD'"),
        ({"granularity": "M5", "candles": []}, "granularity 'M5'"),
        ({"candles": [{"complete": "true"}]}, "complete: expected a boolean"),
        ({"candles": [{"complete": True, "time": "2026-10-09T11:59:00Z"}]}, "mid: expected"),
    ],
)
async def test_oanda_payloads_are_parsed_strictly(body: Any, problem: str) -> None:
    p = oanda(lambda r: status(200, body))
    with pytest.raises(MarketDataError, match=problem):
        await p.history("XAUUSD", FORMING - 5 * MINUTE, FORMING)


async def test_base_url_override_is_used() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return status(200, [])

    p = provider(
        BinanceSpotProvider, handler, {"PUMPUSD": "PUMPUSDT"},
        base_url="https://data-api.binance.vision",
    )  # fmt: skip
    assert await p.history("PUMPUSD", FORMING - 5 * MINUTE, FORMING) == []
    assert hosts == ["data-api.binance.vision"]


async def test_options_control_retries_and_backoff() -> None:
    fake_time = FakeTime()
    p = provider(
        CoinbaseProvider, lambda r: status(503), {"ZECUSD": "ZEC-USD"}, fake_time=fake_time,
        options=ProviderOptions(max_retries=4, backoff_initial_s=1, backoff_max_s=3),
    )  # fmt: skip
    with pytest.raises(MarketDataError, match="gave up after 5 attempts"):
        await p.history("ZECUSD", FORMING - 5 * MINUTE, FORMING)
    assert fake_time.sleeps == [1, 2, 3, 3]


async def test_cdn_errors_are_retried_and_redirects_are_not_followed() -> None:
    fake = CoinbaseFake("ZEC-USD", make_candles(FORMING - 5 * MINUTE, FORMING), SimulatedClock(NOW))
    fake.script.append(status(520, "<html>Web server is returning an unknown error</html>"))
    fake_time = FakeTime()
    p = provider(CoinbaseProvider, fake, {"ZECUSD": "ZEC-USD"}, fake_time=fake_time)
    assert len(await p.history("ZECUSD", FORMING - 5 * MINUTE, FORMING)) == 5
    assert fake_time.sleeps == [0.5]
    moved = provider(
        CoinbaseProvider,
        lambda r: status(301, "", headers={"Location": "https://elsewhere.example/"}),
        {"ZECUSD": "ZEC-USD"},
    )
    with pytest.raises(MarketDataError, match="HTTP 301"):
        await moved.history("ZECUSD", FORMING - 5 * MINUTE, FORMING)
