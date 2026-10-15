"""S3 · Sniper — the port of script 5, "Smart Money Suite v4 [AlgoAlpha]" (doc 13).

Source: ``terminal/pine/received/05_smart_money_suite_v4.pine`` (spec
``terminal/pine/specs/05_smart_money_suite_v4.md``); line numbers below refer to
it. Only the sniper signal and what feeds it are ported; the channel, volume
sentiment, supply/demand, sweeps, key levels, Fib zone, scanner and dashboard are
display or alert only (doc 13 D12).

Every closed bar, in the script's order:

1. ``atr_val = ta.atr(14)`` (L128), ``ema50``/``ema200`` (L174-175);
   ``trend_bull = close > ema50 and ema50 > ema200`` (L179-180).
2. Order blocks (L283-327): ``ta.pivothigh/low(10, 10)``; a confirmed pivot low
   whose candle is bearish pushes its body as a bullish block, a pivot high with a
   bullish candle a bearish one (at most 3 each, oldest shifted out); then every
   block the close has left by 0.05 ATR is deleted.
3. Fair value gaps (L334-370): ``high[2] < low`` pushes a bullish gap, ``low[2] >
   high`` a bearish one (at most 4 each); then the same deletion.
4. BOS (L375-403): ``ta.crossover(close, lsh)`` / ``ta.crossunder(close, lsl)`` are
   evaluated **before** this bar's 40/40 pivots update ``lsh``/``lsl``; levels are
   never consumed; a bullish BOS sets ``upt``, a bearish one clears it.
5. Momentum (L584-587): ``RSI(14) > 55 and close > close[5]`` (``< 45``, ``<``).
6. Score (L594-626): one point each for trend, structure (``upt``, already set by
   this bar's BOS), the close inside a listed block or gap, and momentum.
   ``sniper_long = sniper_bull >= sniper_min and bos_bull`` (L628), short mirrored.
7. Bracket (L645-646, L659-660): stop ``(lsl, else the bar's low) − 0.5 × ATR``,
   target ``close + 2 × (close − stop)``; short mirrored.

Doc 13 D3/D4 apply (README): the entry fills at the next open with the script's
levels, is skipped when that open is already past the stop or target, and a
signal whose stop is not beyond the signal close is not traded; a new signal
while in a trade is ignored (``on_opposite_signal: ignore``).
"""

from collections.abc import Callable
from decimal import Decimal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import (
    Atr,
    Crossover,
    Crossunder,
    Ema,
    History,
    PivotHigh,
    PivotLow,
    Rsi,
    gt,
    lt,
    na,
)
from kterminal.strategies.smc_sniper.zones import (
    Zone,
    ZoneList,
    fair_value_gap,
    order_block,
)
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)

# Fixed in the script (no input): EMA 50/200 (L174-175), RSI 14 with 55/45 and a 5-bar
# ROC (L584-587), the stop 0.5 ATR beyond the swing (L645, L659) and the 2R target.
EMA_FAST = 50
EMA_SLOW = 200
RSI_LENGTH = 14
RSI_BULL = 55.0
RSI_BEAR = 45.0
ROC_BARS = 5
STOP_ATR = 0.5
REWARD_RISK = 2.0

TRIGGER_LONG = "Sniper Long"  # the script's alertcondition titles (L836-837)
TRIGGER_SHORT = "Sniper Short"


class SmcSniperParams(StrategyParams):
    """The script's inputs that change sniper signals (Pine defaults, Pine names)."""

    sniper_min: int = Field(3, ge=1, le=4, description="sniper_min, 'Min Score (1–4)' (L12)")
    fvg_on: bool = Field(
        True, description="fvg_on, 'Show Fair Value Gaps' (L18): off removes FVGs from the score"
    )
    fvg_max: int = Field(4, ge=1, le=8, description="fvg_max, 'Max FVGs Each Side' (L19)")
    ob_on: bool = Field(
        True, description="ob_on, 'Enable Order Blocks' (L79): off removes OBs from the score"
    )
    ob_len: int = Field(10, ge=3, le=500, description="ob_len, 'OB Pivot Lookback' (L80)")
    ob_max: int = Field(3, ge=1, le=8, description="ob_max, 'Max OBs Each Side' (L81)")
    bos_len: int = Field(40, ge=5, le=500, description="bos_len, 'Swing Length' (L88)")
    smb_atr: int = Field(
        14, ge=1, le=1_000, description="smb_atr, 'ATR Length' (L53): the stop's and zones' ATR"
    )


@register_strategy
class SmcSniper(Strategy[SmcSniperParams]):
    meta = StrategyMeta(
        id="smc_sniper",
        name="Smart Money Sniper · BOS + 3-of-4 score (script 5)",
        version="1.0.0",
        description=(
            "Port of 'Smart Money Suite v4 [AlgoAlpha]' sniper: a close crossing the latest "
            "40/40 swing (BOS) with a score of trend, structure, OB/FVG zone and momentum of "
            "at least Min Score; stop beyond the opposite swing ± 0.5 ATR(14), target 2R "
            "(doc 13 S3)."
        ),
        # EMA200 and the Wilder RSI/ATR converge; 81-bar pivot windows and the zone lists
        # fill (spec: >= 600).
        warmup_bars=1_000,
        on_opposite_signal="ignore",  # D4: ignore while in a trade
        skip_entry_beyond_levels=True,  # D3: signals are priced at the bar close
        tags=("pine-port", "script-5", "s3", "smc"),
    )
    Params = SmcSniperParams

    def on_start(self) -> None:
        p = self.params
        self._atr = Atr(p.smb_atr)  # atr_val (L128)
        self._ema50 = Ema(EMA_FAST)  # L174
        self._ema200 = Ema(EMA_SLOW)  # L175
        self._ob_ph = PivotHigh(p.ob_len, p.ob_len)  # ob_ph (L283)
        self._ob_pl = PivotLow(p.ob_len, p.ob_len)  # ob_pl (L284)
        self._sw_hi = PivotHigh(p.bos_len, p.bos_len)  # sw_hi (L375)
        self._sw_lo = PivotLow(p.bos_len, p.bos_len)  # sw_lo (L376)
        self._cx_up = Crossover()  # cx_up = ta.crossover(close, lsh) (L385)
        self._cx_dn = Crossunder()  # cx_dn = ta.crossunder(close, lsl) (L386)
        self._rsi = Rsi(RSI_LENGTH)  # mom_rsi (L584)
        depth = max(p.ob_len, ROC_BARS, 2) + 1
        self._open = History(depth)  # open[ob_len]
        self._close = History(depth)  # close[ob_len], close[5]
        self._high = History(depth)  # high[2]
        self._low = History(depth)  # low[2]
        self.bull_obs = ZoneList(p.ob_max, bullish=True)  # var box[] bull_obs (L286)
        self.bear_obs = ZoneList(p.ob_max, bullish=False)  # bear_obs (L287)
        self.bull_fvgs = ZoneList(p.fvg_max, bullish=True)  # bull_fvgs (L337)
        self.bear_fvgs = ZoneList(p.fvg_max, bullish=False)  # bear_fvgs (L338)
        self.lsh = float("nan")  # var float lsh = na (L378)
        self.lsl = float("nan")  # L379
        self.lshb: int | None = None  # bar index of the lsh pivot (L380)
        self.lslb: int | None = None  # L381
        self.upt = True  # var bool upt = true (L382)

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        bar_index = self.ctx.bar_index
        open_, high, low, close = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        self._open.update(open_)
        self._close.update(close)
        self._high.update(high)
        self._low.update(low)

        atr = self._atr.update(high, low, close)  # L128
        ema50 = self._ema50.update(close)  # L174-175
        ema200 = self._ema200.update(close)
        trend_bull = gt(close, ema50) and gt(ema50, ema200)  # L179
        trend_bear = lt(close, ema50) and lt(ema50, ema200)  # L180

        self._order_blocks(bar_index, high, low, close, atr)  # L283-327
        self._fair_value_gaps(bar_index, high, low, close, atr)  # L334-370

        # L385-403: the crosses see lsh/lsl as they stood before this bar's pivots.
        cx_up = self._cx_up.update(close, self.lsh)
        cx_dn = self._cx_dn.update(close, self.lsl)
        sw_hi = self._sw_hi.update(high)
        sw_lo = self._sw_lo.update(low)
        if not na(sw_hi):
            self.lsh, self.lshb = sw_hi, bar_index - p.bos_len
        if not na(sw_lo):
            self.lsl, self.lslb = sw_lo, bar_index - p.bos_len
        bos_bull = not na(self.lsh) and cx_up  # bos_on is always true here
        bos_bear = not na(self.lsl) and cx_dn
        choch_bull = not self.upt and bos_bull  # chb (L397)
        choch_bear = self.upt and bos_bear  # chs (L398)
        if bos_bull:
            self.upt = True
        if bos_bear:
            self.upt = False

        rsi = self._rsi.update(close)  # L584
        roc = close - self._close[ROC_BARS]  # L585: na for the first 5 bars
        mom_bull = gt(rsi, RSI_BULL) and gt(roc, 0.0)  # L586
        mom_bear = lt(rsi, RSI_BEAR) and lt(roc, 0.0)  # L587

        in_bull = self.bull_obs.containing(close) + self.bull_fvgs.containing(close)
        in_bear = self.bear_obs.containing(close) + self.bear_fvgs.containing(close)
        bull_points = {
            "trend": trend_bull,
            "structure": self.upt,
            "zone": bool(in_bull),
            "momentum": mom_bull,
        }
        bear_points = {
            "trend": trend_bear,
            "structure": not self.upt,
            "zone": bool(in_bear),
            "momentum": mom_bear,
        }
        sniper_bull = sum(bull_points.values())  # L625
        sniper_bear = sum(bear_points.values())  # L626
        sniper_long = sniper_bull >= p.sniper_min and bos_bull  # L628
        sniper_short = sniper_bear >= p.sniper_min and bos_bear  # L629

        context: dict[str, JsonValue] = {
            "ema50": _num(ema50),
            "ema200": _num(ema200),
            "rsi": _num(rsi),
            "roc": _num(roc),
            "atr": _num(atr),
            "lsh": _num(self.lsh),
            "lsl": _num(self.lsl),
            "lsh_bar_index": self.lshb,
            "lsl_bar_index": self.lslb,
            "bar_index": bar_index,
        }
        out: list[Signal] = []
        # Both cannot fire on one bar: a close above lsh and below lsl after crossing
        # both needs a pivot that its own confirmation bar contradicts (README).
        if sniper_long:
            out.append(
                self._entry(True, bar, atr, sniper_bull, bull_points, in_bull, choch_bull, context)
            )
        if sniper_short:
            out.append(
                self._entry(False, bar, atr, sniper_bear, bear_points, in_bear, choch_bear, context)
            )
        return out

    # ── zones (L283-370) ──────────────────────────────────────────────────────
    def _order_blocks(
        self, bar_index: int, high: float, low: float, close: float, atr: float
    ) -> None:
        p = self.params
        ob_ph = self._ob_ph.update(high)  # every bar, like the script's calls
        ob_pl = self._ob_pl.update(low)
        if not p.ob_on:
            return
        pivot_open, pivot_close = self._open[p.ob_len], self._close[p.ob_len]
        pivot_bar = bar_index - p.ob_len
        if not na(ob_pl):  # L289-300
            zone = order_block(pivot_open, pivot_close, bullish=True, bar_index=pivot_bar)
            if zone is not None:
                self.bull_obs.push(zone)
        if not na(ob_ph):  # L302-313
            zone = order_block(pivot_open, pivot_close, bullish=False, bar_index=pivot_bar)
            if zone is not None:
                self.bear_obs.push(zone)
        self.bull_obs.invalidate(close, atr)  # L315-327
        self.bear_obs.invalidate(close, atr)

    def _fair_value_gaps(
        self, bar_index: int, high: float, low: float, close: float, atr: float
    ) -> None:
        if not self.params.fvg_on:
            return
        bull, bear = fair_value_gap(
            self._high[2], self._low[2], high, low, bar_index=bar_index
        )  # L334-356
        if bull is not None:
            self.bull_fvgs.push(bull)
        if bear is not None:
            self.bear_fvgs.push(bear)
        self.bull_fvgs.invalidate(close, atr)  # L358-370
        self.bear_fvgs.invalidate(close, atr)

    # ── the sniper bracket (L641-667) and doc 13 D3 ───────────────────────────
    def _entry(
        self,
        long: bool,
        bar: Bar,
        atr: float,
        score: int,
        points: dict[str, bool],
        zones: list[Zone],
        choch: bool,
        context: dict[str, JsonValue],
    ) -> Signal:
        p = self.params
        ctx = self.ctx
        close, low, high = float(bar.close), float(bar.low), float(bar.high)
        if long:
            basis = self.lsl if not na(self.lsl) else low  # L645
            stop = basis - atr * STOP_ATR
            target = close + REWARD_RISK * (close - stop)  # L646
        else:
            basis = self.lsh if not na(self.lsh) else high  # L659
            stop = basis + atr * STOP_ATR
            target = close - REWARD_RISK * (stop - close)  # L660
        metadata: dict[str, JsonValue] = {
            "pine_signal": "sniper_long" if long else "sniper_short",
            "trigger": TRIGGER_LONG if long else TRIGGER_SHORT,
            "structure_label": "CHoCH" if choch else "BOS",  # L413, L424
            "broken_level": _num(self.lsh if long else self.lsl),
            "score": score,
            "sniper_min": p.sniper_min,
            "points": dict(points),
            "zones": [
                {"kind": z.kind, "top": z.top, "bottom": z.bottom, "bar_index": z.bar_index}
                for z in zones
            ],
            "stop_basis": (
                ("swing_low" if not na(self.lsl) else "bar_low")
                if long
                else ("swing_high" if not na(self.lsh) else "bar_high")
            ),
            **context,
            "script_entry": close,
            "script_stop": _num(stop),
            "script_target": _num(target),
            "risk_distance": _num(abs(close - stop)),
        }
        skip = _invalid_levels(ctx.instrument.round_price, bar.close, stop, target, long)
        if skip is not None:  # D3: the script would still draw the label
            return ctx.no_trade(skip, persist=True, metadata=metadata)
        build = ctx.long if long else ctx.short
        return build(
            stop_loss=stop,
            take_profit=target,
            reason=f"{TRIGGER_LONG if long else TRIGGER_SHORT} {score}/4",
            metadata=metadata,
        )


def _invalid_levels(
    round_price: Callable[[Decimal], Decimal],
    close: Decimal,
    stop: float,
    target: float,
    long: bool,
) -> str | None:
    """Why the script's bracket cannot be traded after rounding to the tick, or None."""
    if na(stop) or na(target):
        return "LEVELS_NA"  # ATR still na: the script's label would read NaN
    if stop <= 0 or target <= 0:
        return "LEVELS_NOT_POSITIVE"
    entry = round_price(close)
    stop_d, target_d = round_price(Decimal(repr(stop))), round_price(Decimal(repr(target)))
    if (stop_d >= entry) if long else (stop_d <= entry):
        return "STOP_WRONG_SIDE"
    if (target_d <= entry) if long else (target_d >= entry):
        return "TARGET_WRONG_SIDE"
    return None


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)
