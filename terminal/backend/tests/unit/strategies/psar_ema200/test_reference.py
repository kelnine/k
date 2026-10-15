"""The PSAR port against an independent transcription of script 4's L600-638 on long
synthetic runs: entries on the script's ``psLong``/``psShort`` bars with the D5 stop, an
exit on every ``psExitLong``/``psExitShort`` bar that meets a matching position."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Dmi, Ema, Sar
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.psar_ema200 import PsarEma200, PsarEma200Params
from tests.fixtures.instruments import T0, XAUUSD
from tests.unit.strategies.pine_port_support import SESSIONS, positions_at_decisions, run

EPS = 1e-10


def gold(seed: int, count: int = 3_000) -> list[Bar]:
    return list(
        synthetic_bars(
            "XAUUSD",
            start=T0,
            count=count,
            start_price=Decimal("2650.00"),
            tick_size=Decimal("0.01"),
            timeframe=Timeframe.parse("15m"),
            seed=seed,
            volatility=0.002,
            regime_change_probability=0.02,
            is_open=SESSIONS.calendar("metals_otc").is_open,
        )
    )


def script(bars: list[Bar], p: PsarEma200Params) -> list[dict[str, Any]]:
    """Per bar: psLong, psShort, psExitLong, psExitShort and the D5 stop of an entry."""
    ema, sar, dmi = (
        Ema(p.ma_slow_length),
        Sar(p.psar_start, p.increment, p.maximum),
        Dmi(p.di_length, p.adx_smoothing),
    )
    in_long = in_short = was_bull = was_bear = False
    out = []
    for bar in bars:
        h, lo, c = float(bar.high), float(bar.low), float(bar.close)
        slow = ema.update(c)
        ps = sar.update(h, lo, c)
        adx = dmi.update(h, lo, c).adx
        bull = ps == ps and c - ps > EPS
        bear = ps == ps and ps - c > EPS
        flip_up, flip_down = bull and not was_bull, bear and not was_bear
        was_bull, was_bear = bull, bear
        trend_up = slow == slow and c - slow > EPS
        trend_down = slow == slow and slow - c > EPS
        strong = adx == adx and adx - p.threshold > EPS
        exit_long, exit_short = in_long and flip_down, in_short and flip_up
        in_long = in_long and not exit_long
        in_short = in_short and not exit_short
        go_long = flip_up and trend_up and strong and not in_long
        go_short = flip_down and trend_down and strong and not in_short
        if go_long:
            in_long, in_short = True, False
        if go_short:
            in_short, in_long = True, False
        stop = sar.projected() if p.stop_mode == "trail" else ps
        out.append(
            {"long": go_long, "short": go_short, "xl": exit_long, "xs": exit_short, "stop": stop}
        )
    return out


@pytest.mark.parametrize(
    "params",
    [{}, {"stop_mode": "trail"}, {"ma_slow_length": 50, "threshold": 25, "maximum": 0.1}],
    ids=["script-defaults", "trail", "other-inputs"],
)
@pytest.mark.parametrize("seed", [6, 7])
def test_port_matches_the_script_transcription(params: dict[str, Any], seed: int) -> None:
    bars = gold(seed)
    p = PsarEma200Params.model_validate(params)
    result = run(PsarEma200, bars, params=params, timeframe="15m")
    assert result.fault is None and result.rejected == []
    expected = script(bars, p)
    index: dict[datetime | None, int] = {bar.open_time: i for i, bar in enumerate(bars)}
    held = positions_at_decisions(bars, result.events)

    got = {
        index[s.bar_time]: s
        for s in result.signals
        if s.signal in (SignalAction.LONG, SignalAction.SHORT, SignalAction.NO_TRADE)
    }
    want = {i: e for i, e in enumerate(expected) if e["long"] or e["short"]}
    assert sorted(got) == sorted(want)
    assert len(want) >= 10
    for i, signal in got.items():
        stop = XAUUSD.round_price(Decimal(repr(want[i]["stop"])))
        if signal.signal is SignalAction.NO_TRADE:  # D3: a trailed stop on the wrong side
            assert p.stop_mode == "trail" and signal.reason == "STOP_WRONG_SIDE"
            assert (stop >= bars[i].close) if want[i]["long"] else (stop <= bars[i].close)
            continue
        assert signal.signal is (SignalAction.LONG if want[i]["long"] else SignalAction.SHORT)
        assert signal.stop_loss == stop

    exits = [(index[s.bar_time], s.signal) for s in result.signals if s.signal.is_exit]
    expected_exits = [
        (i, action)
        for i, e in enumerate(expected)
        for flag, action, side in (
            ("xl", SignalAction.EXIT_LONG, Direction.LONG),
            ("xs", SignalAction.EXIT_SHORT, Direction.SHORT),
        )
        if e[flag] and held[i] is side
    ]
    assert exits == expected_exits
    moves = [s for s in result.signals if s.signal is SignalAction.MOVE_SL]
    assert bool(moves) == (p.stop_mode == "trail")
