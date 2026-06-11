"""Instrument universe and risk configuration.

Five instruments, three playbooks:

- S&P 500 / NASDAQ: mean reversion on 15-minute candles. Indices make
  small overextensions every few hours and tend to snap back.
- Bitcoin: momentum breakouts on the 1-hour. Crypto trends harder than
  indices, so we ride the move instead of fading it.
- Gold / Oil: slower trend following on the 4-hour. Commodities move in
  cleaner waves; intraday whipsaws are noise at this horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    symbol: str           # internal name
    ticker: str           # data-source ticker (Yahoo Finance)
    strategy: str         # "mean_reversion" | "momentum_breakout" | "trend_following"
    timeframe: str        # pandas-style bar size: "15m", "1h", "4h"
    risk_group: str       # correlation bucket for the exposure filter
    allow_short: bool = True
    cost_bps: float = 2.0  # one-way cost per fill: half-spread + slippage + fees


INSTRUMENTS: dict[str, Instrument] = {
    "SPX": Instrument("SPX", "^GSPC", "mean_reversion", "15m", risk_group="risk_on", cost_bps=1.5),
    "NDX": Instrument("NDX", "^IXIC", "mean_reversion", "15m", risk_group="risk_on", cost_bps=2.0),
    "BTC": Instrument("BTC", "BTC-USD", "momentum_breakout", "1h", risk_group="risk_on", cost_bps=8.0),
    "GOLD": Instrument("GOLD", "GC=F", "trend_following", "4h", risk_group="commodity", cost_bps=2.5),
    "OIL": Instrument("OIL", "CL=F", "trend_following", "4h", risk_group="commodity", cost_bps=4.0),
}


@dataclass
class RiskConfig:
    """Account-level risk rules. The 1% stop is hard — no exceptions."""

    starting_equity: float = 100_000.0
    risk_per_trade: float = 0.01        # fraction of equity lost if the stop hits
    atr_stop_multiple: float = 2.0      # stop distance = multiple * ATR
    max_position_leverage: float = 1.0  # notional cap per position, in units of equity
    atr_period: int = 14
    max_positions_per_group: int = 2    # correlation filter: cap same-direction
                                        # positions inside one risk group
    max_open_positions: int = 5


@dataclass
class BotConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    journal_path: str = "journal.csv"
    state_path: str = "bot_state.json"
    ticket_path: str | None = None  # set to emit Liquid order tickets (JSONL)
