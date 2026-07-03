# FutureFi — Indicator Scripts

The complete FutureFi product line as TradingView Pine Script (v6). One file per
product; each script is self-contained, alert-ready, and published as **invite-only**
(see runbook below). Product slugs match `docs/futurefi/01-sitemap.md` and the
`products` table.

## The list

| # | Product | File | Slug | Type | What it does |
|---|---------|------|------|------|--------------|
| 1 | **FutureFi Sniper Pro** | `futurefi-sniper-pro.pine` | `sniper-pro` | Overlay, signals | Trend-filtered pullback entries with auto SL/TP1/TP2 levels, R:R label, and entry alerts. |
| 2 | **FutureFi PA Suite** | `futurefi-pa-suite.pine` | `pa-suite` | Overlay, toolkit | Price-action toolkit: engulfing / pin-bar / inside-bar detection, auto support-resistance zones, session boxes, round-number levels. |
| 3 | **FutureFi Smart Money Pro** | `futurefi-smart-money-pro.pine` | `smart-money-pro` | Overlay, SMC | Full SMC engine — swing structure (HH/HL/LH/LL), BOS/CHoCH, order blocks with mitigation, fair-value gaps with fill tracking, equal highs/lows. Port of the KCharts Phantom Flow engine (`src/indicators/smc.ts`) so web playground and TV render the same logic. |
| 4 | **FutureFi Breakout AI** | `futurefi-breakout-ai.pine` | `breakout-ai` | Overlay, signals | Squeeze/consolidation detection with an adaptive multi-factor breakout score (momentum + volume + volatility expansion + range position); fires only above a confidence threshold, marks retest zones. |
| 5 | **FutureFi Scalper** | `futurefi-scalper.pine` | `scalper` | Overlay, signals | Fast lower-TF entries: EMA ribbon + VWAP bias filter, momentum trigger, session filter, tight ATR targets. Built for 1m–15m. |
| 6 | **FutureFi Swing Pro** | `futurefi-swing-pro.pine` | `swing-pro` | Overlay, signals | Higher-timeframe bias (MTF EMA stack) + structure-break swing entries, wide ATR stops, trade-plan table. Built for 4H–1W. |
| 7 | **FutureFi Dashboard** | `futurefi-dashboard.pine` | `dashboard` | Table | Multi-timeframe overview panel: trend, RSI, momentum, volatility and a composite score per TF (5m→1D) for the current symbol. |

Bundles (`complete-suite`, `ict-pack`, …) are commercial groupings only — no separate script.

## Conventions shared by every script

- `//@version=6`, invite-only publication, overlay unless noted.
- **FF palette:** bull `#22C57A`, bear `#F4506A`, gold `#E8B84B`, muted gray `#8B93A3`
  (matches the FF Obsidian design tokens, doc 03).
- Every entry signal has an `alertcondition` (`Long`, `Short`) so customers can wire
  webhooks; alert messages are JSON-ish (`{{ticker}}`, `{{interval}}` placeholders).
- Inputs are grouped (`Signals`, `Risk`, `Display`) with sane defaults per product's
  target timeframes.
- No `request.security` lookahead (no repaint from HTF); signal candles confirm on bar
  close (`barstate.isconfirmed`) — honesty over eye-candy backtest paint.

## Publishing runbook (per release)

1. Bump the version header comment in the file; keep changelog in
   `docs/futurefi/` product changelog (admin flow, doc 07).
2. Paste into TradingView Pine editor → **Publish script → Invite-only** (first
   release) or **Update** (subsequent). Copy the script's publication id into
   `products.tv_script_id`.
3. Publish version row in `/admin/products/[id]/versions` → triggers customer
   changelog email + Discord webhook.
4. The grant worker (doc 09) manages the invite list from `tv_access_jobs`.

## Parity with KCharts

`futurefi-smart-money-pro.pine` mirrors `src/indicators/smc.ts` (same swing fractal
rule, same last-opposite-candle order block, same 3-candle FVG and mitigation rules).
When one side changes, change the other — the `/playground` demo must match what
customers see on TradingView.
