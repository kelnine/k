"""S10 · Scanner CISD — the MTF scanner's own CISD model of script 1 (doc 13).

Source: ``terminal/pine/received/01_breakout_targets_ict_cisd.pine``, the "MTF scanner"
(L774-1005), spec ``terminal/pine/specs/01_breakout_targets_ict_cisd.md``; line numbers
below refer to the received file. The scanner runs ``scanCisd`` (``scanner.py``) on four
slot timeframes — 5m, 15m, 1h, 4h by default (L101-108) — and grades a slot's signal
**A+** when its direction equals the swing-break bias of every enabled higher slot
(L896-911). This strategy trades the 5m slot's signals on a 5m chart:

* slot 1 (5m) is the chart timeframe, so ``request.security(..., lookahead_off)``
  evaluates it on the chart's own bars (L874-877): the primary series;
* slots 2-4 (15m, 1h, 4h) are higher: ``scanCisd(1)`` with ``lookahead_on`` returns
  each value ``[1]`` — the state after the last slot bar that closed by the chart bar's
  open. Each runs on the bars of ``ctx.series(tf, tradingview_lag=True)``, fed as they
  become visible (doc 05 §5.2.1);
* a new slot-1 signal (L918: ``tm1 != tm1[1]``) is a CISD setup; with ``aplus_only``
  (``aplusOnly``, L111) only an A+ one is traded.

Orders follow doc 13 D7/D4/D3 exactly as S6 (``cisd_sweep.orders``): a limit at the
CISD level, 12-bar expiry, cancelled when TP1 trades first, TP1-only / TP2-only
instances, a new signal replaces the order or trade.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.indicators import na
from kterminal.strategies.cisd_scanner.scanner import ScanCisd, ScanSignal
from kterminal.strategies.cisd_sweep import CisdParams, CisdSetup, CisdTradeStrategy
from kterminal.strategy_engine import StrategyMeta, register_strategy

SLOT_1 = "5m"  # tf1 (L102): the chart timeframe this strategy runs on
HIGHER_SLOTS = ("15m", "1h", "4h")  # tf2, tf3, tf4 (L104-108)

TRIGGER = "Scanner: new signal"  # the script's alertcondition titles (L1003-1005)
TRIGGER_APLUS = "Scanner: new A+ signal"


class CisdScannerParams(CisdParams):
    """The scanner's inputs that change its signals (Pine defaults and names)."""

    aplus_only: bool = Field(
        False, description="aplusOnly (L111): trade only A+ signals (the A+ variant)"
    )
    on2: bool = Field(True, description="on2 (L103): slot 2 (15m) counts for A+")
    on3: bool = Field(True, description="on3 (L105): slot 3 (1h) counts for A+")
    on4: bool = Field(True, description="on4 (L107): slot 4 (4h) counts for A+")


@register_strategy
class CisdScanner(CisdTradeStrategy[CisdScannerParams]):
    meta = StrategyMeta(
        id="cisd_scanner",
        name="Scanner CISD · script 1 MTF scanner (A+ variant)",
        version="1.0.0",
        description=(
            "Port of the MTF scanner of 'Breakout Targets + ICT Levels + CISD': on 5m a close "
            "through the open of the latest opposing run (body >= 0.3 ATR) within 12 bars "
            "of a sweep of the latest 3/3 swing; limit at the CISD level, stop at the run "
            "extreme, TP1 1R / TP2 2R; A+ when the 15m, 1h and 4h swing-break biases agree "
            "(doc 13 S10)."
        ),
        timeframes=(SLOT_1,),
        context_timeframes=HIGHER_SLOTS,
        # 4h bars (the largest timeframe): six days round the clock, plenty for the 3/3
        # swing breaks of the 4h bias; the 5m slot gets 1,728 bars for ATR(14)
        warmup_bars=36,
        on_opposite_signal="reverse",  # D4: market mode reverses on an opposite signal
        skip_entry_beyond_levels=True,  # D3 for market mode (limits are not affected)
        tags=("pine-port", "script-1", "s10", "cisd", "scanner"),
    )
    Params = CisdScannerParams

    def _start_model(self) -> None:
        self.slot1 = self._scan_cisd()
        self.slots = {tf: self._scan_cisd() for tf in HIGHER_SLOTS}
        self._fed: dict[str, datetime | None] = dict.fromkeys(HIGHER_SLOTS)

    def _scan_cisd(self) -> ScanCisd:
        p = self.params
        return ScanCisd(
            min_body=p.min_body,
            req_sweep=p.req_sweep,
            sweep_look=p.sweep_look,
            tp1_r=p.tp1_r,
            tp2_r=p.tp2_r,
        )

    def _evaluate(self, bar: Bar) -> CisdSetup | None:
        self._feed_higher_slots()
        signal = self.slot1.update(
            bar.open_time, float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        )
        if signal is None:
            return None
        aplus, slots = self._aplus(signal.direction)
        if self.params.aplus_only and not aplus:
            return None
        return CisdSetup(
            long=signal.direction > 0,
            entry=signal.cross.level,
            stop=signal.cross.extreme,
            trigger=TRIGGER_APLUS if aplus else TRIGGER,
            pine_signal="scanCisd",
            metadata=self._metadata(signal, aplus, slots),
        )

    def _feed_higher_slots(self) -> None:
        """Run each higher slot on its bars that closed by this bar's open
        (``lookahead_on`` + ``[1]``)."""
        for tf, scan in self.slots.items():
            view = self.ctx.series(tf, tradingview_lag=True)
            count = len(view)
            last = self._fed[tf]
            if count == 0 or (last is not None and view.bar(-1).open_time <= last):
                continue
            fresh: list[Bar] = []
            for i in range(1, count + 1):
                slot_bar = view.bar(-i)
                if last is not None and slot_bar.open_time <= last:
                    break
                fresh.append(slot_bar)
            for slot_bar in reversed(fresh):
                scan.update(
                    slot_bar.open_time,
                    float(slot_bar.open),
                    float(slot_bar.high),
                    float(slot_bar.low),
                    float(slot_bar.close),
                )
            self._fed[tf] = fresh[0].open_time

    def _aplus(self, direction: int) -> tuple[bool, dict[str, JsonValue]]:
        """``aplus(0)`` (L902-911): the slot-1 direction equals the bias of every enabled
        higher slot, and at least one is enabled. Also each slot's row, for metadata."""
        p = self.params
        enabled = dict(zip(HIGHER_SLOTS, (p.on2, p.on3, p.on4), strict=True))
        ok = direction != 0
        counted = 0
        rows: dict[str, JsonValue] = {}
        for tf, scan in self.slots.items():
            if enabled[tf]:
                counted += 1
                if scan.bias != direction:  # nz(bias): 0 before the slot has a bar
                    ok = False
            rows[tf] = {
                "on": enabled[tf],
                "bias": scan.bias,
                "signal": scan.t_dir,
                "signal_age": scan.age,
                "signal_status": scan.status if scan.t_dir else None,
                "signal_time": _iso(scan.t_time),
                "last_bar": _iso(self._fed[tf]),
            }
        return ok and counted > 0, rows

    def _metadata(
        self, signal: ScanSignal, aplus: bool, slots: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        cross = signal.cross
        bar_index = self.slot1.bar_index
        return {
            "model": "scanner",
            "slot": SLOT_1,
            "cisd_level": cross.level,
            "run_extreme": cross.extreme,
            "run_start_bar_index": cross.start,
            "run_bars": bar_index - cross.start + 1,
            "body": signal.body,
            "atr": None if na(signal.atr) else signal.atr,
            "min_body_points": signal.min_body_points,
            "sweep": {
                "bar_index": signal.sweep_bar,
                "bars_ago": bar_index - signal.sweep_bar,
                "level": "swing high" if signal.direction < 0 else "swing low",
                "price": None if na(signal.swept_level) else signal.swept_level,
            },
            "aplus": aplus,
            "aplus_only": self.params.aplus_only,
            "slots": slots,
            "alert_text": self._call_text(signal, aplus),
        }

    def _call_text(self, signal: ScanSignal, aplus: bool) -> str:
        """``callText`` (L887-889): the scanner's alert message for this signal."""
        scan = self.slot1
        text = (
            f"{'A+ ' if aplus else ''}{self.ctx.symbol} {SLOT_1}: "
            f"{'LONG' if signal.direction > 0 else 'SHORT'} CISD  Entry {self._tick(scan.t_entry)}"
            f"  SL {self._tick(scan.t_stop)}  TP1 {self._tick(scan.t_tp1)}"
        )
        return text if na(scan.t_tp2) else f"{text}  TP2 {self._tick(scan.t_tp2)}"

    def _tick(self, value: float) -> str:
        """``str.tostring(p, format.mintick)``; "—" for na (L885)."""
        if na(value):
            return "—"
        return str(self.ctx.instrument.round_price(Decimal(repr(value))))


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
