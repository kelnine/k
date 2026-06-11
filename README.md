# Multi-instrument trading bot

A paper-trading bot that watches five instruments with three playbooks, sizes
every position off ATR, never risks more than 1% per trade, and sends two
messages a day. Claude Code writes and updates the logic; the bot just
executes.

> **This is a paper-trading simulator for education and research.** It places
> no real orders. Markets routinely take money from strategies that look
> clever in a backtest — do not wire this to real funds expecting the
> Instagram version of the results.

## The playbook

| Instrument | Ticker | Strategy | Timeframe | Why |
|---|---|---|---|---|
| S&P 500 | ^GSPC | Mean reversion | 15m | Indices overextend every few hours and snap back |
| NASDAQ | ^IXIC | Mean reversion | 15m | Same fade, tech flavour |
| Bitcoin | BTC-USD | Momentum breakout | 1h | Crypto trends harder — ride the move, don't fade it |
| Gold | GC=F | Trend following | 4h | Commodities move in cleaner waves |
| Oil | CL=F | Trend following | 4h | Slow layer avoids intraday whipsaw noise |

## Risk rules (the part that actually matters)

- **ATR-based sizing per instrument** — size is inversely proportional to
  volatility, so a quiet day on gold gets a bigger position than a wild day
  on bitcoin, and the money at risk is identical either way.
- **Hard 1% stop, no exceptions** — every position carries a stop placed
  2×ATR away and sized so that hitting it costs exactly 1% of equity. Stops
  are checked before strategies get a say (`engine.py` step 1).
- **Correlation filter** — if S&P and NASDAQ are already long, a new bitcoin
  long is the same risk-on bet a third time and gets skipped. Risk groups
  and caps live in `config.py`.
- **Costs are modelled, not ignored** — every fill pays a per-instrument
  one-way cost (half-spread + slippage + fees, in bps). P&L and the journal
  are net. On the synthetic demo this turns +0.9% gross into −7.5% net,
  which is the honest number and the reason high-turnover strategies need
  a real edge, not a plausible one.
- **Leverage cap** — notional per position is capped at 1× equity; a tight
  stop on a quiet instrument no longer implies size the account couldn't
  actually carry.

## The two daily messages

- **7am briefing** — last price, day-over-day move, volatility regime, and
  what's currently held, per instrument.
- **9pm recap** — trades closed today with reasons, P&L, open risk, equity.

Messages print to stdout and `messages.log`; set `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` to also receive them on your phone.

## Run it

```bash
pip install -r requirements.txt

pytest                     # 21 tests, all offline (synthetic data)
python run_backtest.py     # backtest the whole book on recent Yahoo data
python run_bot.py          # live paper-trading loop (polls every 15 min)
```

## Forward test on Liquid (paper)

Set `BotConfig.ticket_path` and the engine appends an order ticket to
`tickets.jsonl` for every entry/exit it takes — instrument mapped to its
Liquid market (`tradingbot/liquid.py`), sized in USD by the same risk
engine, stop-loss attached. In a Claude session connected to the Liquid
MCP server (with paper trading enabled), Claude turns unprocessed tickets
into `suggest_trade` confirmation cards; nothing executes until you press
Confirm. A suggestion is not an execution, and the hard stop rides along.

## Layout

```
tradingbot/
  config.py        instruments, timeframes, risk groups, risk knobs
  indicators.py    ATR, RSI, z-score, EMA, Donchian
  strategies/      mean_reversion, momentum_breakout, trend_following
  risk.py          position sizing, hard stop maths, correlation filter
  broker.py        paper broker: positions, stop checks, trade journal (CSV)
  engine.py        per-bar orchestration: stops -> exits -> filtered entries
  backtest.py      bar-by-bar backtester reusing the live engine
  reports.py       7am briefing and 9pm recap
  notify.py        stdout/file/Telegram delivery
run_bot.py         live paper loop
run_backtest.py    backtest CLI
```

The journal every closed trade lands in is `journal.csv` — entry, exit, stop,
P&L, equity after, and the human-readable reason for both ends of the trade.
