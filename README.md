# AI Financial Terminal

Interactive financial terminal built from the **4 Master Prompts** of the
*AI Financial Terminal* guide. Each module is a self-contained HTML file (HTML + CSS + JavaScript,
no external dependencies) with a professional dark theme and realistic simulated data.

## Modules

| File | Module | Description |
|---|---|---|
| `index.html` | 📊 Market Dashboard | Major indices (S&P 500, NASDAQ, Dow, Russell 2000, VIX, FTSE, DAX, Nikkei) with price, daily change, 5-session sparklines, market open/closed status and auto-refresh every 30 s. |
| `analyzer.html` | 🔎 Stock Analyzer | Search any ticker (AAPL, TSLA, BTC-USD…) and get basic data, technical analysis (RSI, MACD, SMAs, support/resistance), fundamentals (P/E, EPS, dividends, ROE/ROA) and an executive summary with a BUY/HOLD/SELL signal. |
| `macro.html` | 🌍 Macroeconomic Analysis | Plain-language executive summary, global risk traffic light, key indicators (Fed, CPI/PCE, NFP, GDP, ISM), global markets, Treasury yield curve, economic calendar and a "what this means for you" educational section. |
| `portfolio.html` | 💼 Portfolio Analysis | Editable positions table (demo pre-loaded), summary, allocation by asset/sector/geography, risk analysis (volatility, Sharpe, drawdown, beta), S&P 500 comparison, AI recommendations and an exportable report (PDF / copy summary). |

## How to view it

It's a 100 % static site: download the repository and open `index.html` in any browser,
or serve it with `python3 -m http.server` and visit `http://localhost:8000`.

## Design

- `#0A0A0A` background, `#00C896` green accents, terminal-style monospace typography.
- Color coding: green = positive, red = negative, yellow = neutral.
- Responsive (desktop and mobile). Charts drawn with native `<canvas>`.

> ⚠️ All data is **simulated** for demo purposes and does not constitute financial advice.
