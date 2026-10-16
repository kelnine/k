"""S12 · Wyckoff Auto entry — the port of script 6, "Wyckoff [theUltimator5]" (doc 13).

Source: ``terminal/pine/received/06_wyckoff_theultimator5.pine`` (spec
``terminal/pine/specs/06_wyckoff_theultimator5.md``); line numbers below refer to it.
``wyckoff_engine.py`` runs the script's chart-timeframe campaign engine (``f_engine``,
L1060-1764) on every closed bar; this module turns its Auto entry (L1729-1747) and its
structure events into signals:

* **Entry** — on the bar where ``f_engine`` sets ``s.entryTime`` (the script's
  "Wyckoff: long entry" / "Wyckoff: short entry" alert, L2236-2238, L3198-3199) for the
  chosen Entry Strictness: a market order at the next open, long for an accumulation
  outcome, short for a distribution outcome.
* **Stop** (doc 13 D5) — the campaign's hard level (``f_hardLevel`` for the outcome side,
  L723-729: the Spring/UTAD extreme, else the more extreme of the original and the current
  range edge) ∓ 0.5 × ATR(14) of the signal bar, fixed for the life of the trade. The
  script has no stop.
* **Exits** (D5) — only the script's own structure events of the campaign the trade came
  from: invalidation (RS_INVALID, two closes beyond the hard level by 0.5 ATR, L1198-1215),
  the D→B demotion (three closes back past the range middle, L1210-1218), Phase E failure
  (the same rule in Phase E, L1221) or Phase E older than 300 bars (L1222), and its
  replacement by a new climax (L1237, L1260-1271). Each is a ``FLATTEN`` at the next open
  with the event in its metadata. The ``2R`` variant adds a fixed target at twice the
  risk from the signal close; the script has none.

Doc 13 D3 and D4 apply (README): the entry is skipped when the next open is already past
the stop or target (``skip_entry_beyond_levels``) and not sent when the stop is on the
wrong side of the signal close; a new entry while a trade is open is ignored
(``on_opposite_signal: ignore``).
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import na
from kterminal.strategies.wyckoff_auto.state import (
    DIR_ACCUM,
    DIR_NAMES,
    DIR_NONE,
    ENTRY_NAMES,
    EVENT_NAMES,
    PHASE_NAMES,
    TYPE_NAMES,
    WS,
    bit_names,
)
from kterminal.strategies.wyckoff_auto.wyckoff_engine import (
    RESEED,
    CampaignEnd,
    EngineStep,
    EntryCheck,
    Strictness,
    WyckoffEngine,
    confidence,
    hard_level,
    type_ws,
)
from kterminal.strategy_engine import (
    PositionEvent,
    PositionEventKind,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)

Target = Literal["structure", "2R"]

REWARD_RISK = 2.0  # the D5 variant's fixed target, in R
TRIGGER_LONG = "Wyckoff: long entry"  # the script's alertcondition titles (L3198-3199)
TRIGGER_SHORT = "Wyckoff: short entry"

# The structure events that close a trade (D5), by the engine's campaign-end kind.
EXIT_EVENTS = {
    "RS_INVALID": "INVALIDATION",
    "RS_DEMOTE": "DEMOTION",
    RESEED: "REPLACED_BY_CLIMAX",
}
_ENTRY_DROPPED = (PositionEventKind.ORDER_CANCELLED, PositionEventKind.ORDER_EXPIRED)
EXIT_REASONS = {
    "INVALIDATION": "campaign invalidated: two closes beyond the hard level by 0.5 ATR",
    "DEMOTION": "Phase D demoted to B: three closes back past the range middle",
    "PHASE_E_FAILURE": "Phase E failed: three closes back past the range middle",
    "PHASE_E_TIMEOUT": "Phase E older than 300 bars",
    "REPLACED_BY_CLIMAX": "campaign replaced by a new climax",
}


class WyckoffAutoParams(StrategyParams):
    """Entry Strictness, the script's only input that changes the Auto entry (L28), and
    the doc 13 D5 choices."""

    entry_strictness: Strictness = Field(
        "Standard",
        description=(
            "entryStrictness, 'Entry Strictness' (L28): Conservative (LPS/LPSY, confidence "
            ">= 75, readiness >= 7, validation >= 60), Standard (Phase C test or LPS/LPSY, "
            "60 / 6 / 50) or Aggressive (any Phase C test, or SOS/SOW without a test, "
            "55 / 5 / 50)"
        ),
    )
    target: Target = Field(
        "structure",
        description=(
            "structure: no target, the trade ends at its stop or on the campaign's "
            "structure events (D5); 2R: plus a fixed target at 2 x the risk from the "
            "signal close (D5 variant)"
        ),
    )
    stop_atr: float = Field(
        0.5,
        gt=0,
        le=10,
        allow_inf_nan=False,
        description=(
            "D5: the stop sits this many ATR(14) beyond the campaign's hard level, like "
            "the script's own invalidation buffer (structureInvalidationATR, L78)"
        ),
    )


@dataclass(slots=True)
class _Trade:
    """The campaign a sent entry came from: its structure events end the trade."""

    serial: int
    direction: int
    bar_index: int
    opened: bool = False  # the theoretical book filled the entry
    stale: bool = False  # the campaign went stale (RS_STALE) while the trade was open


@register_strategy
class WyckoffAuto(Strategy[WyckoffAutoParams]):
    meta = StrategyMeta(
        id="wyckoff_auto",
        name="Wyckoff Auto entry · campaign engine (script 6)",
        version="1.0.0",
        description=(
            "Port of 'Wyckoff [theUltimator5]': the chart-timeframe campaign engine "
            "(climax, AR, ST, Phase B, Spring/UTAD, Phase C test, SOS/SOW, LPS/LPSY, "
            "Phase E) and its Auto entry for the chosen Entry Strictness; stop 0.5 ATR "
            "beyond the campaign's hard level, exits on the campaign's structure events "
            "(doc 13 S12, D5)."
        ),
        # The engine is path-dependent from its first bar: SMA200 + 20 bars, ATR and
        # effort averages over 50 and a 25-80-bar trend window before the first climax,
        # then a campaign needs 30+ bars of Phase B (spec: >= 300 bars, more for parity).
        warmup_bars=1_000,
        on_opposite_signal="ignore",  # D4: scripts 5, 6, 8, 9 ignore until flat
        skip_entry_beyond_levels=True,  # D3: the script prices the entry at the close
        tags=("pine-port", "script-6", "s12", "wyckoff"),
    )
    Params = WyckoffAutoParams

    def on_start(self) -> None:
        ctx = self.ctx
        self._engine = WyckoffEngine(
            float(ctx.instrument.tick_size),
            float(ctx.timeframe.seconds),
            self.params.entry_strictness,
        )
        self._trade: _Trade | None = None

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        """Follow the trade in the theoretical book: once it has closed (stop, target or a
        structure exit) or its entry was skipped, the campaign no longer owns a trade."""
        trade = self._trade
        if trade is None:
            return None
        if event.kind is PositionEventKind.OPENED:
            trade.opened = True
        elif event.kind is PositionEventKind.CLOSED and trade.opened:
            self._trade = None
        elif event.kind in _ENTRY_DROPPED and not trade.opened:
            self._trade = None  # D3: the next open was already past the stop or target
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        ctx = self.ctx
        step = self._engine.update(
            ctx.bar_index,
            bar.open_time.timestamp() * 1000.0,  # Pine's time: the bar open in ms
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            float(bar.volume),
        )
        if ctx.warming_up:
            return None  # signals are discarded; no trade to follow yet
        trade = self._trade
        if (
            trade is not None
            and not trade.opened
            and ctx.bar_index > trade.bar_index
            and ctx.position is None
            and ctx.pending_entry is None
        ):
            # The market entry would have filled at this bar's open: the book refused it
            # (a venue refusal, e.g. the market was closed at the decision).
            self._trade = None
        out: list[Signal] = []
        exit_signal = self._structure_exit(step)
        if exit_signal is not None:
            out.append(exit_signal)
        check = step.entry_check
        if check is not None and check.taken:
            out.append(self._entry(bar, step, check))
        return out

    # ── D5: exits on the campaign's own structure events ─────────────────────────────────
    def _structure_exit(self, step: EngineStep) -> Signal | None:
        trade = self._trade
        if trade is None:
            return None
        event: str | None = None
        end: CampaignEnd | None = None
        for candidate in step.ends:
            if candidate.serial != trade.serial:
                continue
            if candidate.kind == "RS_STALE":
                trade.stale = True  # not an exit: the trade keeps its stop (README)
                continue
            if candidate.kind == "RS_EEND":
                event = "PHASE_E_FAILURE" if candidate.detail.get("e_fail") else "PHASE_E_TIMEOUT"
            else:
                event = EXIT_EVENTS.get(candidate.kind)
            if event is not None:
                end = candidate
                break
        if event is None and step.seeded != DIR_NONE and step.serial != trade.serial:
            # a new climax seeds a campaign while the trade's campaign is gone (it went
            # stale) or is being replaced: "campaign replacement by a new climax"
            event = "REPLACED_BY_CLIMAX"
        if event is None:
            return None
        self._trade = None
        position = self.ctx.position
        metadata: dict[str, JsonValue] = {
            "trigger": "structure exit",
            "exit_event": event,
            "pine_event": end.kind if end is not None else RESEED,
            "detail_text": EXIT_REASONS[event],
            "campaign_serial": trade.serial,
            "campaign_phase": PHASE_NAMES[end.phase] if end is not None else None,
            "campaign_outcome": DIR_NAMES[end.outcome] if end is not None else None,
            "campaign_went_stale": trade.stale,
            "trade_direction": "long" if trade.direction == DIR_ACCUM else "short",
            "entry_bar_index": trade.bar_index,
            "values": _json_detail(end.detail) if end is not None else {},
            "new_climax": _new_climax(step),
            "position_entry": None if position is None else str(position.entry_price),
            "bar_index": self.ctx.bar_index,
            "atr": _num(step.m.a),
        }
        return self.ctx.flatten(reason=f"Wyckoff: {EXIT_REASONS[event]}", metadata=metadata)

    # ── the Auto entry (L1729-1747) with the D5 stop ──────────────────────────────────────
    def _entry(self, bar: Bar, step: EngineStep, check: EntryCheck) -> Signal:
        ctx = self.ctx
        p = self.params
        s = self._engine.s
        m = step.m
        long = check.direction == DIR_ACCUM
        hard = hard_level(s, check.direction)
        if long:
            stop = hard - m.a * p.stop_atr
            target = m.close + REWARD_RISK * (m.close - stop) if p.target == "2R" else math.nan
        else:
            stop = hard + m.a * p.stop_atr
            target = m.close - REWARD_RISK * (stop - m.close) if p.target == "2R" else math.nan
        metadata: dict[str, JsonValue] = {
            "trigger": TRIGGER_LONG if long else TRIGGER_SHORT,
            "pine_signal": check.triggers[0],
            "pine_triggers": list(check.triggers),
            "entry_kind": ENTRY_NAMES[check.kind],
            "entry_strictness": check.strictness,
            "events": list[JsonValue](bit_names(step.sig)),
            "confidence": check.confidence,
            "min_confidence": check.min_confidence,
            "validation": check.validation,
            "validation_floor": check.validation_floor,
            "readiness": check.readiness,
            "min_readiness": check.min_readiness,
            "campaign": _campaign(s),
            "hard_level": _num(hard),
            "stop_basis": _stop_basis(s, check.direction),
            "stop_atr": p.stop_atr,
            "atr": _num(m.a),
            "trend_score": _num(m.trend_score),
            "regime": self._engine.regime,
            "swing_length": m.p_len,
            "effort": "range" if m.no_vol else "volume",  # D9: the feed's volume
            "bar_source": bar.source,
            "bar_index": ctx.bar_index,
            "target_mode": p.target,
            "script_entry": _num(m.close),  # entryPrice = close (L1746)
            "script_stop": _num(stop),
            "script_target": _num(target),
            "risk_distance": _num(abs(m.close - stop)),
        }
        skip = self._invalid_levels(long, bar.close, stop, target)
        if skip is not None:  # D3: no trade with the stop on the wrong side
            return ctx.no_trade(skip, persist=True, metadata=metadata)
        self._trade = _Trade(serial=step.serial, direction=check.direction, bar_index=m.bar_index)
        build = ctx.long if long else ctx.short
        side = "long" if long else "short"
        return build(
            stop_loss=stop,
            take_profit=None if na(target) else target,
            reason=f"Wyckoff {side} entry: {ENTRY_NAMES[check.kind]} ({check.strictness})",
            metadata=metadata,
        )

    def _invalid_levels(self, long: bool, close: Decimal, stop: float, target: float) -> str | None:
        """Why the levels cannot be traded after rounding to the tick, or None."""
        if na(stop):
            return "LEVELS_NA"  # no hard level: the campaign has no range edge yet
        if stop <= 0 or (not na(target) and target <= 0):
            return "LEVELS_NOT_POSITIVE"
        round_price = self.ctx.instrument.round_price
        entry = round_price(close)
        stop_d = round_price(Decimal(repr(stop)))
        if (stop_d >= entry) if long else (stop_d <= entry):
            return "STOP_WRONG_SIDE"
        if not na(target):
            target_d = round_price(Decimal(repr(target)))
            if (target_d <= entry) if long else (target_d >= entry):
                return "TARGET_WRONG_SIDE"
        return None


def _campaign(s: WS) -> dict[str, JsonValue]:
    """The campaign behind an entry, for 'explain this trade'."""
    return {
        "serial": s.serial,
        "type": TYPE_NAMES[type_ws(s)],
        "climax": "SC" if s.stop_side == DIR_ACCUM else "BC",
        "outcome": DIR_NAMES[s.outcome],
        "phase": PHASE_NAMES[s.phase],
        "last_event": EVENT_NAMES[s.ev],
        "climax_time": _iso(s.climax_time),
        "climax_price": _num(s.climax_price),
        "climax_score": s.climax_score,
        "preliminary_time": _iso(s.ps_time),
        "preliminary_price": _num(s.ps_price),
        "ar_time": _iso(s.ar_time),
        "ar_price": _num(s.ar_price),
        "range_high": _num(s.range_high),
        "range_low": _num(s.range_low),
        "orig_high": _num(s.orig_high),
        "orig_low": _num(s.orig_low),
        "st_count": s.st_count,
        "opposite_tests": s.opp_count,
        "traversals": s.trav_count,
        "phase_b_start": _iso(s.b_start_time),
        "phase_c_start": _iso(s.c_start_time),
        "phase_d_start": _iso(s.d_start_time),
        "spring_utad": s.exc,
        "spring_utad_tested": s.exc_tested,
        "spring_utad_time": _iso(s.exc_time),
        "spring_utad_price": _num(s.exc_price),
        "test_time": _iso(s.test_time),
        "test_price": _num(s.test_price),
        "test_score": s.test_score,
        "sos_sow_time": _iso(s.str_time),
        "sos_sow_price": _num(s.str_price),
        "sos_sow_score": s.str_score,
        "lps_time": _iso(s.lps_time),
        "lps_price": _num(s.lps_price),
        "lps_score": s.lps_score,
        "swing_length": s.piv_len,
        "birth_trend": _num(s.birth_trend),
        "confidence": confidence(s),
    }


def _stop_basis(s: WS, side: int) -> str:
    """Which level ``f_hardLevel`` returned (L726, L728)."""
    if s.exc and s.outcome == side and not na(s.exc_price):
        return "spring" if side == DIR_ACCUM else "utad"
    return "range_low" if side == DIR_ACCUM else "range_high"


def _new_climax(step: EngineStep) -> dict[str, JsonValue] | None:
    if step.seeded == DIR_NONE:
        return None
    return {"side": "SC" if step.seeded == DIR_ACCUM else "BC", "serial": step.serial}


def _json_detail(detail: dict[str, float | int | bool | str | None]) -> dict[str, JsonValue]:
    out: dict[str, JsonValue] = {}
    for key, value in detail.items():
        if isinstance(value, float):
            out[key] = _num(value)
        elif isinstance(value, int) and not isinstance(value, bool) and key == "new_side":
            out[key] = DIR_NAMES.get(value, str(value))
        else:
            out[key] = value
    return out


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)


def _iso(ms: float) -> str | None:
    """A Pine ``time`` value (ms since the epoch) as an ISO time, na as null."""
    if na(ms):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()
