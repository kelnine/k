"""S6 against an independent transcription of script 1's main CISD model on long synthetic runs.

``transcribe`` re-implements, in plain procedural code and without the port's classes or
the engine's session and period helpers, the lines the model executes: the 5/5 pivots
by window (L192-193), ``ta.atr(14)`` as Wilder's RMA with ``nz`` (L194, L631), the New
York sessions by local wall-clock minute (L477-537), PDH/PWH/PMH on the 17:00 New York
trading day (or UTC midnight) with a partial first period left out (L400-402), the
sweeps (L585-624), the runs and the CISD with consumption, the bear-first rule and the
signal window applied last (L629-683). The port must signal the same CISDs on the same
bars with the same level and stop.

The data are synthetic 5m random walks from 1 March to 10 April 2026: the New York clock
change of 8 March (London 02:00 starts at 03:00 EDT that night), a weekly and a monthly
boundary for the previous-period levels, round the clock and with the gold calendar's
closed weekends and daily breaks.
"""

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.cisd_sweep import CisdSweep
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import real_catalog, run

EPS = 1e-10
NAN = math.nan
NY = ZoneInfo("America/New_York")
START = datetime(2026, 2, 28, 22, 0, tzinfo=UTC)  # 17:00 New York: a trading day starts

Setup = tuple[int, bool, float, float]  # bar index, long, CISD level, stop


def gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > EPS


def lt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b < -EPS


def ge(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b >= -EPS


def le(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b <= EPS


def pivot(values: list[float], i: int, left: int, right: int, highs: bool) -> float:
    """``ta.pivothigh/low`` on bar ``i``: >= on the left, strictly beyond on the right."""
    if i < left + right:
        return NAN
    p = i - right
    v = values[p]
    lefts, rights = values[p - left : p], values[p + 1 : i + 1]
    if highs and all(v >= x for x in lefts) and all(v > x for x in rights):
        return v
    if not highs and all(v <= x for x in lefts) and all(v < x for x in rights):
        return v
    return NAN


def wall_minute(t: datetime) -> int:
    local = t.astimezone(NY)
    return local.hour * 60 + local.minute


def ny_trading_day(t: datetime) -> date:
    """17:00 New York rollover: a bar opening at or after 17:00 belongs to the next day."""
    return (t.astimezone(NY) + timedelta(hours=7)).date()


def ny_day_start(day: date) -> datetime:
    previous = day - timedelta(days=1)
    return datetime.combine(previous, time(17, 0), tzinfo=NY).astimezone(UTC)


def utc_trading_day(t: datetime) -> date:
    return t.astimezone(UTC).date()


def utc_day_start(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=UTC)


SESSIONS = {"asia": (1200, 1440), "lon": (120, 300), "nyam": (570, 720), "nypm": (810, 960)}


def transcribe(
    bars: list[Bar],
    *,
    trading_day: Callable[[datetime], date] = ny_trading_day,
    day_start: Callable[[date], datetime] = ny_day_start,
    pv: tuple[int, int] = (5, 5),
    min_body: float = 0.3,
    sweep_look: int = 12,
    req_sweep: bool = True,
    window: str = "Any time",
) -> list[Setup]:
    o = [float(b.open) for b in bars]
    h = [float(b.high) for b in bars]
    lo = [float(b.low) for b in bars]
    c = [float(b.close) for b in bars]
    show = bars[0].timeframe.seconds <= 3600
    out: list[Setup] = []
    atr = NAN
    trs: list[float] = []
    inside_prev = dict.fromkeys(SESSIONS, False)
    ranges = {k: [NAN, NAN] for k in ("asia", "lon", "nyam")}
    current: dict[str, list[Any]] = {}  # period -> [key, high, low, complete]
    previous: dict[str, list[Any]] = {}
    last_ph = last_pl = NAN
    bsl_bar = ssl_bar = -100000
    bull_open = bear_open = NAN
    bull_x = bear_x = -1
    bull_high = bear_low = NAN
    prev_bull = prev_bear = False
    for i, bar in enumerate(bars):
        # ta.atr(14): RMA of the true range (high - low on the first bar)
        tr = h[i] - lo[i]
        if i > 0:
            tr = max(tr, abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        trs.append(tr)
        if i == 13:
            atr = sum(trs) / 14
        elif i > 13:
            atr = (atr * 13 + tr) / 14
        ph = pivot(h, i, pv[0], pv[1], True)
        pl = pivot(lo, i, pv[0], pv[1], False)
        # sessions by New York wall-clock minute of the open
        minute = wall_minute(bar.open_time)
        inside = {k: a <= minute < b for k, (a, b) in SESSIONS.items()}
        for k in ranges:
            if inside[k] and not inside_prev[k]:
                ranges[k] = [h[i], lo[i]]
            elif inside[k]:
                ranges[k] = [max(ranges[k][0], h[i]), min(ranges[k][1], lo[i])]
        # previous day / week / month
        day = trading_day(bar.open_time)
        keys = {"D": day, "W": day - timedelta(days=day.weekday()), "M": day.replace(day=1)}
        for period, key in keys.items():
            running = current.get(period)
            if running is not None and running[0] == key:
                running[1], running[2] = max(running[1], h[i]), min(running[2], lo[i])
                continue
            if running is not None and running[3]:
                previous[period] = running
            complete = i > 0 or bar.open_time == day_start(key)
            current[period] = [key, h[i], lo[i], complete]
        levels_h = [previous[p][1] if p in previous else NAN for p in "DWM"]
        levels_l = [previous[p][2] if p in previous else NAN for p in "DWM"]
        for k in ranges:
            live = show and not inside[k]
            levels_h.append(ranges[k][0] if live else NAN)
            levels_l.append(ranges[k][1] if live else NAN)
        # sweeps
        if not math.isnan(ph):
            last_ph = ph
        if not math.isnan(pl):
            last_pl = pl
        prev_h = h[i - 1] if i else NAN
        prev_l = lo[i - 1] if i else NAN
        bsl = gt(h[i], last_ph) or any(gt(h[i], v) and le(prev_h, v) for v in levels_h)
        ssl = lt(lo[i], last_pl) or any(lt(lo[i], v) and ge(prev_l, v) for v in levels_l)
        if bsl:
            bsl_bar, last_ph = i, NAN
        if ssl:
            ssl_bar, last_pl = i, NAN
        # runs and CISD
        bull_bar, bear_bar = gt(c[i], o[i]), lt(c[i], o[i])
        if bull_bar and not prev_bull:
            bull_open, bull_x, bull_high = o[i], i, h[i]
        elif not math.isnan(bull_open):
            bull_high = max(bull_high, h[i])
        if bear_bar and not prev_bear:
            bear_open, bear_x, bear_low = o[i], i, lo[i]
        elif not math.isnan(bear_open):
            bear_low = min(bear_low, lo[i])
        prev_bull, prev_bear = bull_bar, bear_bar
        big = ge(abs(c[i] - o[i]), min_body * (0.0 if math.isnan(atr) else atr))
        bear_cisd = bull_cisd = False
        level = stop = NAN
        if not math.isnan(bull_open) and i > bull_x and lt(c[i], bull_open):
            bear_cisd = big and (not req_sweep or i - bsl_bar <= sweep_look)
            level, stop = bull_open, bull_high
            bull_open = NAN
        if not bear_cisd and not math.isnan(bear_open) and i > bear_x and gt(c[i], bear_open):
            bull_cisd = big and (not req_sweep or i - ssl_bar <= sweep_look)
            level, stop = bear_open, bear_low
            bear_open = NAN
        in_window = {
            "NY AM": inside["nyam"],
            "NY AM + NY PM": inside["nyam"] or inside["nypm"],
            "London + NY AM": inside["lon"] or inside["nyam"],
            "London + NY AM + NY PM": inside["lon"] or inside["nyam"] or inside["nypm"],
        }.get(window, True) or not show
        if in_window and (bear_cisd or bull_cisd):
            out.append((i, bull_cisd, level, stop))
        inside_prev = inside
    return out


def port_setups(result: Any) -> list[Setup]:
    out = []
    for s in result.signals:
        meta = s.metadata
        if meta.get("pine_signal") in ("bullCisd", "bearCisd"):
            out.append(
                (
                    meta["bar_index"],
                    meta["pine_signal"] == "bullCisd",
                    meta["script_entry"],
                    meta["script_stop"],
                )
            )
    return out


def swept_levels(result: Any) -> list[str]:
    """The names of the levels taken by the sweeps behind every CISD of a run."""
    names = []
    for s in result.signals:
        sweep = s.metadata.get("sweep")
        if isinstance(sweep, dict):
            names += [str(level["level"]) for level in sweep["levels"]]
    return names


def walk(
    instrument: Instrument, *, seed: int, timeframe: str = "5m", days: int = 41, calendar: bool
) -> list[Bar]:
    tf = Timeframe.parse(timeframe)
    is_open = None
    if calendar:
        is_open = real_catalog().sessions.calendar(instrument.trading_hours).is_open
    return list(
        synthetic_bars(
            instrument.symbol,
            start=START,
            count=int(days * 86_400 / tf.seconds),
            start_price=Decimal("2650"),
            tick_size=instrument.tick_size,
            timeframe=tf,
            volatility=0.0015,
            seed=seed,
            is_open=is_open,
        )
    )


@pytest.mark.parametrize("calendar", [False, True], ids=["24x7", "gold-calendar"])
@pytest.mark.parametrize("seed", [3, 11])
def test_port_matches_the_transcription_with_script_defaults(seed: int, calendar: bool) -> None:
    bars = walk(XAUUSD, seed=seed, calendar=calendar)
    expected = transcribe(bars)
    result = run(CisdSweep, bars)
    assert result.fault is None and result.rejected == []
    assert len(expected) > 100  # a CISD every few hours on a random walk
    assert port_setups(result) == expected
    swept = set(swept_levels(result))
    # every kind of level was swept at least once in these 41 days
    assert {"pivot high", "pivot low", "PDH", "PDL", "PWH", "PWL", "Asia high", "Asia low"} <= swept


@pytest.mark.parametrize(
    ("params", "kwargs"),
    [
        ({"sig_window": "NY AM"}, {"window": "NY AM"}),
        ({"sig_window": "London + NY AM"}, {"window": "London + NY AM"}),
        ({"sig_window": "NY AM + NY PM"}, {"window": "NY AM + NY PM"}),
        ({"sig_window": "London + NY AM + NY PM"}, {"window": "London + NY AM + NY PM"}),
        ({"req_sweep": False, "min_body": 0.0}, {"req_sweep": False, "min_body": 0.0}),
        ({"pv_l": 3, "pv_r": 7, "sweep_look": 4}, {"pv": (3, 7), "sweep_look": 4}),
        ({"min_body": 0.8}, {"min_body": 0.8}),
    ],
    ids=["ny-am", "london-ny-am", "ny-am-pm", "all-three", "no-filters", "pivots-3-7", "body-0.8"],
)
def test_port_matches_the_transcription_for_each_input(
    params: dict[str, Any], kwargs: dict[str, Any]
) -> None:
    bars = walk(XAUUSD, seed=5, calendar=True)
    expected = transcribe(bars, **kwargs)
    result = run(CisdSweep, bars, params=params)
    assert result.fault is None and result.rejected == []
    assert expected and port_setups(result) == expected


def test_crypto_days_roll_at_utc_midnight_and_sessions_run_every_day() -> None:
    btc = real_catalog().instrument("BTCUSD")
    bars = walk(btc, seed=8, calendar=False, days=20)
    expected = transcribe(bars, trading_day=utc_trading_day, day_start=utc_day_start)
    result = run(CisdSweep, bars, instrument=btc, params={"sig_window": "London + NY AM"})
    assert result.fault is None and result.rejected == []
    assert port_setups(result) == transcribe(
        bars, trading_day=utc_trading_day, day_start=utc_day_start, window="London + NY AM"
    )
    assert len(run(CisdSweep, bars, instrument=btc).signals) > 0 and expected


@pytest.mark.parametrize("timeframe", ["15m", "1h", "4h"])
def test_other_timeframes_and_no_session_levels_above_60_minutes(timeframe: str) -> None:
    bars = walk(XAUUSD, seed=13, calendar=True, timeframe=timeframe, days=60)
    params = {"sig_window": "NY AM"}
    result = run(CisdSweep, bars, params=params, timeframe=timeframe)
    assert result.fault is None and result.rejected == []
    expected = transcribe(bars, window="NY AM")
    assert expected and port_setups(result) == expected
    if timeframe == "4h":  # showSess off: no session levels, the window is ignored
        levels = [s.metadata["levels"] for s in result.signals if "levels" in s.metadata]
        assert all(lv["Asia high"] is None and lv["NY AM low"] is None for lv in levels)  # type: ignore[index, call-overload]


def test_previous_month_levels_are_swept_like_the_script() -> None:
    # from 1 February (31 January 17:00 New York, a complete month) to mid-April: PMH/PML
    # of February and March are live in March and April
    bars = list(
        synthetic_bars(
            "XAUUSD",
            start=datetime(2026, 1, 31, 22, 0, tzinfo=UTC),
            count=70 * 288,
            start_price=Decimal("2650"),
            tick_size=XAUUSD.tick_size,
            timeframe=Timeframe.parse("5m"),
            volatility=0.0015,
            seed=1,
        )
    )
    result = run(CisdSweep, bars)
    assert result.fault is None and result.rejected == []
    assert port_setups(result) == transcribe(bars)
    swept = swept_levels(result)
    assert "PMH" in swept and "PML" in swept
