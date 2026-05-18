# Perpetual Futures Trading Bot

Modular Python trading bot for perpetual futures — **paper-trading mode by default**.  
Hyperliquid live execution is available but requires explicit opt-in.

---

## Project Structure

```
├── config/
│   └── settings.yaml        # all tuneable parameters
├── strategy/
│   ├── indicators.py        # EMA 9/21/50/200, RSI, ADX, ATR, volume ratio
│   ├── structure.py         # BOS, CHoCH, Order Blocks, FVG, Liquidity Sweeps
│   └── engine.py            # confluence scoring → Signal
├── risk/
│   └── engine.py            # position sizing, daily loss, kill switch
├── execution/
│   ├── paper.py             # simulated fills, SL/TP management, CSV + JSON
│   └── hyperliquid.py       # Hyperliquid DEX adapter (disabled by default)
├── alerts/
│   └── telegram.py          # signal, entry, SL, TP, PnL, risk alerts
├── data/
│   └── feed.py              # ccxt Bybit feed + synthetic fallback
├── logs/                    # runtime output (gitignored except .gitkeep)
├── main.py                  # live bot entry point
├── backtest.py              # historical replay engine
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# edit .env — only needed for live trading or Telegram alerts
```

### 3. Review `config/settings.yaml`

Key parameters to review before running:

| Parameter | Default | Description |
|---|---|---|
| `mode` | `paper` | `paper` or `live` |
| `symbols` | `[BTC-PERP, ETH-PERP]` | Symbols to trade |
| `timeframe` | `15m` | Candle timeframe |
| `paper_trading.starting_balance` | `10000` | Simulated account balance |
| `risk.max_daily_loss_pct` | `3.0` | Kill switch trigger |
| `risk.max_trade_size_pct` | `2.0` | % of account risked per trade |
| `risk.max_leverage` | `10` | Hard leverage cap |
| `risk.max_open_positions` | `3` | Concurrent position limit |

### 4. Run paper trading

```bash
python main.py
```

### 5. Run backtest

```bash
python backtest.py                          # all configured symbols, 1000 bars
python backtest.py --symbol BTC-PERP --limit 2000
```

Backtest output:
- `logs/bt_BTC_PERP_trades.csv` — trade-by-trade history
- `logs/bt_BTC_PERP_dashboard.json` — summary stats

---

## Strategy Logic

Signals require a minimum **confluence score** (default: 4) across:

| Component | Max pts | Description |
|---|---|---|
| EMA alignment | 2 | Full 9>21>50>200 stack |
| EMA short-term | 1 | 9>21 + price vs EMA50 |
| Price vs EMA200 | 1 | Bias filter |
| RSI | 2 | Oversold/overbought extremes |
| RSI mid-range | 1 | Recovering / extended |
| ADX | 1 | Trend strength ≥ threshold |
| Volume spike | 1 | Volume > N× 20-bar average |
| BOS | 2 | Break of structure |
| CHoCH | 3 | Change of character (trend flip) |
| Liquidity sweep | 2 | Sweep + reversal setup |
| Order block | 2 | Price at unmitigated OB |
| FVG | 1 | Price inside fair value gap |

### TP / SL levels (ATR-based)

| Level | Multiplier |
|---|---|
| Stop Loss | 1.5× ATR |
| TP1 (trail SL to BE) | 2.0× ATR |
| TP2 (full close) | 3.5× ATR |

---

## Risk Rules

All rules are enforced before any order is placed:

- **Max daily loss** — kill switch fires when daily PnL < -N% of account
- **Max trade size** — position sized so SL hit = N% of account
- **Max leverage** — capped conservatively based on SL distance
- **Max open positions** — hard limit on concurrent trades
- **Stop loss required** — every trade must have a valid SL
- **Kill switch** — set `risk.kill_switch: true` or activated automatically
- **No-trade mode** — observe signals without executing

---

## Telegram Alerts

1. Create a bot via [@BotFather](https://t.me/botfather) → copy the token
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot)
3. Set in `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC-xxxxx
TELEGRAM_CHAT_ID=987654321
```

4. Enable in config:

```yaml
alerts:
  telegram:
    enabled: true
```

Alert types: `📡 SIGNAL`, `🟢/🔴 ENTRY`, `🛑 STOP LOSS`, `✅ TP HIT`,
`📈 PNL UPDATE`, `⚠️ RISK WARNING`, `🚨 KILL SWITCH`

---

## Live Trading on Hyperliquid

> **Warning**: Live trading involves real funds. Test thoroughly on testnet first.

1. Install the SDK:

```bash
pip install hyperliquid-python-sdk eth-account
```

2. Set credentials in `.env`:

```env
HYPERLIQUID_PRIVATE_KEY=your_hex_private_key_no_0x
HYPERLIQUID_WALLET_ADDRESS=0xYourWalletAddress
```

3. Enable in `config/settings.yaml`:

```yaml
mode: live

execution:
  hyperliquid:
    enabled: true
    testnet: true   # set false for mainnet — irreversible
```

4. Start on **testnet first**:

```bash
python main.py
```

---

## Output Files

| File | Contents |
|---|---|
| `logs/bot.log` | Full structured log |
| `logs/trade_history.csv` | Every closed paper trade |
| `logs/dashboard.json` | Live dashboard snapshot (balance, win rate, open trades) |

### `dashboard.json` schema

```json
{
  "updated_at": "2025-01-01T00:00:00",
  "balance": 10350.00,
  "initial_balance": 10000.00,
  "total_pnl": 350.00,
  "total_pnl_pct": 3.5,
  "open_positions": 1,
  "total_trades": 12,
  "win_rate_pct": 58.3,
  "avg_win_usd": 120.50,
  "avg_loss_usd": -65.20,
  "open_trades": [...]
}
```

---

## Environment Variables Reference

| Variable | Required | Purpose |
|---|---|---|
| `HYPERLIQUID_PRIVATE_KEY` | Live only | EVM private key |
| `HYPERLIQUID_WALLET_ADDRESS` | Live only | Wallet address |
| `TELEGRAM_BOT_TOKEN` | Alerts only | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Alerts only | Your Telegram chat ID |

**Never commit `.env` or private keys to version control.**

---

## Adding New Strategies

1. Add scoring logic in `strategy/engine.py` → `_score_and_build()`
2. Add indicator calculations in `strategy/indicators.py`
3. Add structure detectors in `strategy/structure.py`

The `Signal` dataclass carries `entry_price`, `stop_loss`, `take_profit_1`,
`take_profit_2`, `confidence`, and `reasons` — all downstream components
(risk, execution, alerts) consume this object unchanged.
