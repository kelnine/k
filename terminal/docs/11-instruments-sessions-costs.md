# 11. Instruments, Symbols, Sessions & Costs

The terminal never assumes that every market works the same way. Forex, CFDs,
futures and crypto differ in tick size, contract size, quantity units,
trading hours, fees, funding and — above all — in what each venue calls them.
Everything below is **configuration** in `terminal/config/catalog/*.yaml`,
loaded and validated at start-up, applied to the database with
`kterminal catalog apply`, and fingerprinted so every trade records exactly
which specification it was sized and costed with.

## 11.1 Three layers: instrument → venue → listing

```
            canonical instrument                listing (venue-specific contract)
            ─────────────────────              ─────────────────────────────────────────────
 strategy ─▶ MNQ   (Nasdaq-100 micro future) ─┬▶ cme:MNQ            MNQZ6   tick 0.25  $2/pt
                                              ├▶ tradovate:MNQ      MNQZ6
                                              └▶ tradingview:MNQ    CME_MINI:MNQ1!   (data only)
            NEARUSD (NEAR priced in USD)     ─┬▶ binance_usdm:NEARUSD   NEARUSDT perp, funding 8h
                                              ├▶ bybit_linear:NEARUSD   NEARUSDT
                                              └▶ binance_spot:NEARUSD   NEARUSDT
            XAUUSD (gold spot)               ─┬▶ generic_mt5_cfd:XAUUSD   100 oz / lot
                                              └▶ oanda:XAUUSD            XAU_USD, units
```

| Layer | Holds | Example |
|---|---|---|
| **Instrument** (canonical) | asset class, base/quote currency, canonical tick (for rounding strategy prices), default trading hours, trading-day rule, underlying group, futures contract cycle | `MNQ`: INDEX, USD, tick 0.25, `cme_globex_equity`, rollover 17:00 New York, quarterly H/M/U/Z, third-Friday expiry, roll 8 days before |
| **Venue** | kind (exchange / broker / prop firm / data feed / signal source / simulator), platform (MT5, TradeLocker, Tradovate, Rithmic, ProjectX, Binance, Bybit, OKX, Hyperliquid, OANDA, TradingView …), server time zone, broker symbol suffixes | `generic_mt5_cfd`: PROP_FIRM on MT5 |
| **Listing** | venue symbol, contract type (SPOT, CFD, FUTURE, PERPETUAL, INDEX_DATA), tick size, contract size / multiplier, quantity unit and step, min/max quantity, min notional, P&L currency, trading-hours override, cost profile, dated-symbol format for futures, verification date and source | `binance_usdm:NEARUSD`: `NEARUSDT`, PERPETUAL, tick 0.001, step 1, USDT, `binance_usdm_taker` |

Strategies only ever see canonical symbols. Adapters translate to and from
venue symbols. A prop-firm server whose gold contract is 100 oz and another
whose index CFD is $1 per point are simply two listings with different specs;
nothing in the code changes.

**Money math** uses the listing, never the instrument:
`P&L = Δprice × quantity × contract_size` (in the listing's quote currency,
converted to the account currency with configurable rates; USDT and USDC
default to 1 USD as an explicit, recorded assumption). Quantities are always
rounded **down** to the listing's step so sizing never exceeds the risk budget.
Inverse (coin-margined) contracts are recognised but refused for sizing until
they are implemented.

## 11.2 Symbol mapping and aliases

`InstrumentCatalog.resolve_symbol(raw, source)` turns whatever arrives —
`BINANCE:NEARUSDT.P`, `NEAR`, `US100`, `CME_MINI:MNQ1!`, `XAUUSD.r` — into the
canonical instrument:

1. normalise: trim, upper-case, remember an `EXCHANGE:` prefix;
2. exact alias for that source (e.g. `tradingview: CME_MINI:MNQ1!`);
3. the same without the exchange prefix and without TradingView's `.P`
   perpetual suffix;
4. venue symbols and per-listing aliases of that venue, after stripping the
   venue's configured broker suffixes (`.r`, `m`, `.pro` …);
5. global aliases (`GOLD`, `US100`, `NEAR`) and canonical symbols.

An alias that points to two instruments within one source is a catalog
validation error; an unknown symbol is rejected with close-match suggestions.
The reverse direction, `venue_symbol(instrument, venue, on=date)`, returns the
symbol to send to a venue — for futures it resolves the front contract for
that date (e.g. `MNQ` → `MNQZ6` on CME/Tradovate, `MNQZ2026` on TradingView)
using the contract cycle and roll rule.

## 11.3 Sessions, time zones and DST

All instants are stored in UTC. Every *local* rule names an IANA time zone and
is evaluated with `zoneinfo`, so daylight-saving changes are handled by the
time-zone database rather than by hard-coded offsets.

| Concept | Purpose | Example |
|---|---|---|
| **Trading calendar** (trading hours) | When a venue/instrument is open: weekly intervals in local time plus holiday closures and early closes; or 24/7 | `cme_globex_equity` (America/Chicago): Sun 17:00 → Mon 16:00, … Thu 17:00 → Fri 16:00 |
| **Trading-day rule** | Which trading day an instant belongs to (daily P&L, daily loss limits, daily bars, swap) | `ny_1700`: a new day starts at 17:00 America/New_York; `utc_midnight` for crypto |
| **Session window** | Named local-time windows strategies and analytics use: ORB ranges, kill zones, the London / New York sessions | `ny_orb_15`: 09:30–09:45 America/New_York, Mon–Fri; `london_open`: 08:00–09:00 Europe/London |
| **Session classification** | An ordered list of windows that labels each trade's session for analytics | `asia`, `london`, `new_york` |

DST rules, precisely:

* A window is defined in *its own* time zone. `london_open` is 08:00 London
  time all year; in New York time it moves between 03:00 and 04:00, including
  the weeks in March and October/November when the US and UK switch on
  different dates.
* A window whose end is not after its start crosses midnight (e.g. Asia
  19:00–03:00 New York).
* A local time that does not exist (the spring-forward gap) is shifted
  forward by the gap; an ambiguous local time (the autumn fall-back hour)
  resolves to its first occurrence. Both cases are covered by tests.

America/New_York is the reference zone for most of the configured rules
(17:00 New York rollover, the New York open at 09:30), but nothing is
hard-wired to it.

## 11.4 Transaction costs

Each listing points at a **cost profile**; an account's venue profile decides
which listing (and therefore which costs) it simulates. Cost components are
independent and configurable:

| Component | Models | Applied |
|---|---|---|
| Spread | `fixed` (price units), `fixed_ticks`, `session` (different spread per session window, e.g. wider in Asia), `quotes` (real bid/ask, default as fallback) | Market fills cross half the spread. Stop levels are bid (sell stop) / ask (buy stop) prices, as on MT5: a stop triggers when that side of the spread reaches it and fills there (or at the opening bid/ask if the bar gaps through it), so the spread is paid once. Targets trigger only when the far side of the spread reaches them |
| Commission | `none`, `per_quantity` (per lot / per contract per side — futures exchange + clearing + NFA + broker fees), `notional` (maker/taker rate of notional — crypto), optional minimum per order | Each fill |
| Slippage | `none`, `fixed_ticks`, `notional_bps` | Adverse, on market and stop fills only (never on limit fills) |
| Funding (perpetuals) | `none`, `constant` (rate per interval, interval hours, UTC anchor hours — e.g. 8 h at 00/08/16 or hourly) | Each funding time a position is open; positive rate = longs pay shorts |
| Swap / overnight financing (CFD, FX) | `none`, `points` (price points per lot per night, long/short), `annual_rate` (of notional) with rollover time/zone and a triple-charge weekday | Each rollover a position is held through |

Sign convention: commissions are non-negative fees; funding and swap are
signed cash flows (negative = paid by the account). All amounts are in the
listing's quote currency and are written to the account ledger separately, so
the analytics can report spread, commission, slippage, funding and swap costs
per strategy.

## 11.5 Venue profiles: identical conditions

A **venue profile** maps each canonical instrument to the listing whose
specification and costs an account simulates (and, optionally, a separate
listing to source bars from). Every lab account references one, so two
strategies are only compared as "identical conditions" when their accounts use
the same venue profile, starting balance and account configuration version.

```yaml
venue_profiles:
  - id: lab_default
    description: Shared simulated conditions for strategy-lab paper accounts
    execution:
      XAUUSD: generic_mt5_cfd:XAUUSD
      MNQ: cme:MNQ
      NEARUSD: binance_usdm:NEARUSD
```

Changing a cost assumption creates a new catalog fingerprint; trades keep the
fingerprint they were made with.
