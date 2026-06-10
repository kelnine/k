# Signal Funnel Bot

A profitable rebuild of a free crypto-signals Telegram channel. Unlike the
typical "free signals" channel — which only earns from exchange referral links —
this one runs a **funnel**: free teaser signals for reach, **exchange referral
links** for passive revenue, and a paid **VIP tier** (Telegram Stars) for
recurring revenue. Signals are **auto-generated** from a real positioning-data
engine, and every call is tracked into a public win-rate so the channel earns
trust.

👉 See [`BUSINESS.md`](BUSINESS.md) for the model, unit economics, and compliance.

## What it does

- ⏱️ Scans a watchlist on a schedule and generates signals (direction, entry,
  stop, TP1/TP2, confidence, leverage).
- 🧠 Real edge: when positioning data is available it **fades crowded retail and
  follows whales**, blended with momentum + funding — not random "37%".
- 🆓 Posts **teasers** to the free channel (TP2 hidden) and **full** signals to
  the VIP channel.
- ⭐ Sells VIP via **Telegram Stars** (no merchant account), auto-grants private
  channel access on payment.
- 🔗 Referral footer on every post using your exchange affiliate code.
- 📊 Logs every call and posts a weekly **track record**.
- 👥 Per-user referral deep links (invite friends → free VIP).

## Architecture

```
datasources.py  →  market data (Binance public  OR  Co-Invest "Liquid" engine)
strategy.py     →  snapshot → Signal (the edge)
formatter.py    →  Signal → Telegram message (styled, with referral footer)
store.py        →  subs, referrals, track record (SQLite)
main.py         →  scheduler, commands, Telegram Stars payments
```

Two market-data backends behind one interface:
- **`binance`** — public REST, zero config, runs today (price/change/funding/OI).
- **`liquid`** — the Co-Invest engine, which adds whale-vs-retail **positioning
  bias** (the real edge) and a built-in referral code. Set `DATA_SOURCE=liquid`
  + `LIQUID_BASE_URL`/`LIQUID_TOKEN`.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in BOT_TOKEN, FREE_CHANNEL, referral links

# Preview signals WITHOUT a bot token:
python scripts/preview.py --sample   # offline, canned positioning data
python scripts/preview.py            # live Binance data

# Run the bot:
python -m bot.main
```

### Telegram setup
1. Create the bot with [@BotFather](https://t.me/BotFather) → put token in `.env`.
2. Create a public channel + a private VIP channel; add the bot as **admin** to
   both. Put their handles/ids in `FREE_CHANNEL` / `VIP_CHANNEL`.
3. Replace the placeholder `REF_*` links with your real exchange affiliate URLs.
4. `python -m bot.main`.

## ⚠️ Disclaimer

Educational software. Signals are not financial advice (NFA). Exchange links are
referral links. You are responsible for legal/regulatory compliance in your
jurisdiction — see the compliance section in `BUSINESS.md`.
