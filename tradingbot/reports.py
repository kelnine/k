"""The two daily messages.

- 7am briefing: what's happening in the market — last price, day-over-day
  move, volatility regime, and what the bot is currently holding.
- 9pm recap: how the bot did — trades closed today, P&L, open risk.

Both return plain text; `notify.py` decides where the text goes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .broker import PaperBroker
from .config import Instrument
from .indicators import atr
from .strategies.base import LONG


def morning_briefing(
    data: dict[str, pd.DataFrame],
    instruments: dict[str, Instrument],
    broker: PaperBroker,
    now: datetime,
) -> str:
    lines = [f"Good morning — market briefing for {now:%A %d %b %Y}", ""]
    for sym, inst in instruments.items():
        df = data.get(sym)
        if df is None or len(df) < 30:
            lines.append(f"  {sym}: no data")
            continue
        last = float(df["close"].iloc[-1])
        day_ago = df["close"].loc[: df.index[-1] - timedelta(days=1)]
        ref = float(day_ago.iloc[-1]) if len(day_ago) else float(df["close"].iloc[0])
        chg = (last / ref - 1) * 100
        vol_now = float(atr(df, 14).iloc[-1])
        vol_avg = float(atr(df, 14).tail(100).mean())
        regime = "volatile" if vol_now > 1.25 * vol_avg else (
            "quiet" if vol_now < 0.8 * vol_avg else "normal")
        pos = broker.positions.get(sym)
        held = (
            f"holding {'long' if pos.direction == LONG else 'short'} from {pos.entry_price:.2f}"
            if pos
            else "flat"
        )
        lines.append(f"  {sym}: {last:,.2f} ({chg:+.2f}% vs yesterday), {regime} — {held}")
    lines += ["", f"Equity: {broker.equity:,.2f}. Plan: {len(broker.positions)} open position(s), "
              "stops in place, nothing to do on your side."]
    return "\n".join(lines)


def evening_recap(broker: PaperBroker, now: datetime) -> str:
    today = [t for t in broker.closed_trades if t.closed_at.date() == now.date()]
    pnl = sum(t.pnl for t in today)
    wins = sum(1 for t in today if t.pnl > 0)
    lines = [f"Evening recap — {now:%A %d %b %Y}", ""]
    if today:
        lines.append(f"  Closed {len(today)} trade(s): {wins} winners, "
                     f"net {pnl:+,.2f}")
        for t in today:
            side = "long" if t.direction == LONG else "short"
            lines.append(
                f"    {t.symbol} {side}: {t.entry_price:.2f} -> {t.exit_price:.2f} "
                f"= {t.pnl:+,.2f} ({t.exit_reason})"
            )
    else:
        lines.append("  No trades closed today — the bot sat on its hands, which is a position too.")
    lines += [
        "",
        f"  Open positions: {len(broker.positions)}",
        f"  Equity: {broker.equity:,.2f}",
    ]
    return "\n".join(lines)
