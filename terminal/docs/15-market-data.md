# 15. Market Data

The market-data layer (`kterminal/marketdata`) is where real bars enter the
terminal: closed 1-minute bars per canonical instrument, downloaded from venue
APIs or read from imported files, for live paper trading (polling) and for
warm-up and backtests (history). Every higher timeframe is then built from
these 1m bars by the one aggregator described in
[12-strategy-lab](12-strategy-lab.md#125-flow-through-the-lab).

Everything here is **read-only**. Providers only download candles; no setting,
token or command in this layer can place an order, and LIVE execution remains
unimplemented.

| Piece | Module | Purpose |
|---|---|---|
| Port | `marketdata/base.py` | `MarketDataProvider`, `MarketDataError` |
| Data source map | `config/catalog/data_sources.yaml`, `marketdata/sources.py` | Which provider serves each instrument, under which symbol, with which volume |
| Providers | `marketdata/providers/` | Binance USD-M, Binance spot, Bybit linear, Coinbase, Hyperliquid, OANDA, CSV files |
| Factory | `marketdata/factory.py` | `build_providers(settings, sources, catalog)` → providers keyed by instrument |
| CSV import | `marketdata/csv_import.py` | Generic OHLCV files and TradingView chart exports |
| CLI | `kterminal data sources`, `kterminal data fetch` | Inspect the map; download history to CSV |

## 15.1 The port

```python
class MarketDataProvider(Protocol):
    name: str
    def supports(self, instrument: str) -> bool: ...
    async def history(self, instrument: str, start: datetime, end: datetime) -> list[Bar]: ...
    async def latest(self, instrument: str, since: datetime) -> list[Bar]: ...
    async def aclose(self) -> None: ...
```

Every provider follows the same rules:

* instruments are **canonical** (`XAUUSD`, `BTCUSD`); the provider maps them to
  its own symbols (`XAU_USD`, `BTCUSDT`) through the data source map;
* only **closed** bars are returned: a bar counts as closed once its minute has
  ended plus `close_delay_s` (default 2 s, for clock skew and late prints),
  measured on an injected `Clock`; bars the venue still flags as incomplete
  (OANDA `complete: false`) are dropped as well;
* bars are 1m, **oldest first**, `open_time` on the minute, with
  `start <= open_time < end` for `history` and `open_time >= since` for
  `latest`; a start inside a minute begins at the next whole minute;
* missing minutes are **not** filled in (TradingView does not fill them either);
* prices and volumes are **exact decimals** as the venue sent them — JSON is
  decoded with `parse_float=Decimal`, so even Coinbase's JSON numbers never go
  through a float;
* `Bar.source` is the provider's name (`binance_usdm`, `oanda`, `csv` …), so the
  origin of every bar is recorded;
* failures raise `MarketDataError` with the provider, the request and the
  venue's own error text.

## 15.2 The data source map

`terminal/config/catalog/data_sources.yaml` maps each canonical instrument to
its source. It sits next to the catalog and is validated against it on every
load, but it is not part of the catalog document or its fingerprint (the
catalog loader skips the file).

```yaml
data_sources:
  BTCUSD:
    provider: binance_usdm      # binance_usdm | binance_spot | bybit_linear | coinbase |
                                # hyperliquid | oanda | csv
    symbol: BTCUSDT             # the provider's own symbol
    volume: exchange            # exchange | tick | none — what Bar.volume means
    note: Binance USD-M perpetual = TradingView BINANCE:BTCUSDT.P.
    alternatives:               # optional, tried in order (15.2.2)
      - {provider: coinbase, symbol: BTC-USD, volume: exchange, note: USD spot}
```

The map is strict, like the catalog. `DataSourceMap.load(path, catalog)`
reports every problem at once: unknown or duplicate keys (a YAML key given
twice is an error, not "the last one wins"), missing fields, values that are not
strings, unknown instruments (with close-match suggestions), unknown providers,
a volume kind the provider cannot deliver (OANDA is always `tick`, the
exchanges always `exchange`), a symbol that does not look like the provider's
(`BTCUSDT` for Coinbase), a provider listed twice for one instrument, and a
symbol that differs from the catalog's listing of the same instrument at the
same venue (`binance_usdm:NEARUSD` is `NEARUSDT`, so the map must say
`NEARUSDT`).

### 15.2.1 Defaults

The primary sources are the feeds the `lab_default` venue profile charts on
TradingView (`venue_profiles.yaml`, `data:` comments), so bars fetched here are
the same series a TradingView chart of that symbol shows.

| Instrument | Provider | Symbol | Volume | TradingView feed |
|---|---|---|---|---|
| XAUUSD | oanda | `XAU_USD` | tick | OANDA:XAUUSD |
| XAGUSD | oanda | `XAG_USD` | tick | OANDA:XAGUSD |
| NAS100 | oanda | `NAS100_USD` | tick | OANDA:NAS100USD |
| US30 | oanda | `US30_USD` | tick | OANDA:US30USD |
| US500 | oanda | `SPX500_USD` | tick | OANDA:SPX500USD |
| EURUSD | oanda | `EUR_USD` | tick | OANDA:EURUSD |
| GBPUSD | oanda | `GBP_USD` | tick | OANDA:GBPUSD |
| BTCUSD | binance_usdm | `BTCUSDT` | exchange | BINANCE:BTCUSDT.P |
| NEARUSD | binance_usdm | `NEARUSDT` | exchange | BINANCE:NEARUSDT.P |
| SOLUSD | bybit_linear | `SOLUSDT` | exchange | BYBIT:SOLUSDT.P |
| ZECUSD | coinbase | `ZEC-USD` | exchange | COINBASE:ZECUSD |
| HYPEUSD | hyperliquid | `HYPE` | exchange | HYPERLIQUID:HYPEUSDC.P |
| PUMPUSD | binance_spot | `PUMPUSDT` | exchange | BINANCE:PUMPUSDT |
| MNQ | csv | `CME_MINI:MNQ1!` | exchange | CME_MINI:MNQ1! (exports) |
| NQ | csv | `CME_MINI:NQ1!` | exchange | CME_MINI:NQ1! (exports) |

**OANDA: mid prices, tick volume.** OANDA candles are requested with
`price=M` (mid). A paper account fills at the mid plus half the spread from its
cost profile ([11.4](11-instruments-sessions-costs.md#114-transaction-costs)),
so bid or ask candles would charge part of the spread twice. TradingView's
OANDA charts may plot a different price component (not verified); a parity run
must compare like with like. OANDA's `volume` is the number of price updates in
the minute — **tick volume**, not traded size — so volume-driven logic on these
instruments runs on tick volume and is labelled as such (doc 13, D9).

**MNQ / NQ** have no free 1-minute API. They are served by the `csv` provider
from imported files — TradingView exports of the continuous front-month series
until a paid CME vendor is chosen (doc 13, D1).

### 15.2.2 Switching providers

An instrument's `alternatives` are used, in order, when the provider above them
is **disabled** on this host (`KT_MARKETDATA__DISABLED_PROVIDERS`) or **not
configured** (no OANDA token, no CSV directory). This is how a host in a
country that Binance or Bybit geo-blocks keeps BTCUSD, NEARUSD and SOLUSD:

```bash
KT_MARKETDATA__DISABLED_PROVIDERS=binance_usdm,binance_spot,bybit_linear
kterminal data sources        # BTCUSD → coinbase BTC-USD (alternative: binance_usdm is disabled)
```

`kterminal data fetch BTCUSD --provider coinbase …` uses one alternative for a
single download. To switch an instrument for good, swap its primary and the
alternative in the YAML file.

An alternative is a **different market** — spot instead of a perpetual, USD
instead of USDT, another order book — so its bars are close to, never
identical with, the primary's. `Bar.source` records which one produced each
bar; results from different sources are not "identical conditions".

## 15.3 Providers

| Provider | Endpoint | Auth | Max per request (used) | Order | Forming bar | History | Venue limit (budget used) |
|---|---|---|---|---|---|---|---|
| `binance_usdm` | `GET fapi.binance.com/fapi/v1/klines` | — | 1,500 (1,500) | oldest first | when the range reaches it | since listing | 2,400 weight/min per IP; 1,500 rows weigh 10 (1,200/min) |
| `binance_spot` | `GET api.binance.com/api/v3/klines` | — | 1,000 (1,000) | oldest first | when the range reaches it | since listing | 6,000 weight/min per IP; a request weighs 2 (1,200/min) |
| `bybit_linear` | `GET api.bybit.com/v5/market/kline?category=linear` | — | 1,000 (1,000) | **newest first** | first in the list when the range reaches it | since listing | 600 requests / 5 s per IP (300 requests/min) |
| `coinbase` | `GET api.exchange.coinbase.com/products/{id}/candles?granularity=60` | — | 300 (299) | **newest first** | may be included | years | ~10 requests/s per IP (180 requests/min) |
| `hyperliquid` | `POST api.hyperliquid.xyz/info` `candleSnapshot` | — | 5,000 (5,000) | oldest first | included | **latest 5,000 candles only** (≈ 3.5 days of 1m) | 1,200 weight/min per IP; 20 + 1 per 60 candles (600/min) |
| `oanda` | `GET /v3/instruments/{instrument}/candles?granularity=M1&price=M` | bearer token | 5,000 (4,999) | oldest first | `complete: false` | years | ~120 requests/s (600 requests/min) |
| `csv` | `<csv_dir>/<INSTRUMENT>.csv` | — | — | file order | whatever the file holds | the file | — |

Response shapes, as parsed (strictly: a missing or malformed field is an
error, never a default):

* **Binance** — `[[open_ms, "o", "h", "l", "c", "volume", close_ms, …]]`; the close
  time must be `open + 59 999 ms` (anything else is not a 1m kline). With
  `startTime` and `endTime` the endpoint returns the oldest rows from
  `startTime` without passing `endTime`. Volume in the base asset.
* **Bybit** — `{"retCode": 0, "result": {"symbol", "category", "list":
  [["start_ms", "o", "h", "l", "c", "volume", "turnover"], …]}}`, every value a
  string; `start` is inclusive on the candle start. Errors arrive inside HTTP 200
  as `retCode ≠ 0`.
* **Coinbase** — `[[time_s, low, high, open, close, volume], …]` with JSON
  numbers — note **low and high come before open**. Ranges above 300 buckets are
  rejected; minutes without trades have no candle.
* **Hyperliquid** — `[{"t", "T", "s", "i", "o", "c", "h", "l", "v", "n"}]`; the
  interval must be `1m`, the coin the requested one and `T = t + 59 999`.
  Builder-deployed (HIP-3) markets are addressed as `dex:COIN`.
* **OANDA** — `{"instrument", "granularity": "M1", "candles": [{"complete",
  "volume", "time": "…T…:00.000000000Z", "mid": {"o", "h", "l", "c"}}]}`; times
  must be RFC 3339 UTC on a whole minute.
* **CSV** — see 15.7. ISO times without an offset are read as UTC, so keep
  TradingView's default unix-time export format. A file is re-read only when its
  size or modification time changes; live polling sees new bars only when the
  file is replaced with a newer export.

### Geo-restrictions and errors that are not retried

| Venue | Signal | Meaning |
|---|---|---|
| Binance (both) | HTTP **451** "restricted location" | The host's country is not served (e.g. the US). Disable the provider; alternatives take over |
| Binance | HTTP 418 | The IP is banned for ignoring 429s (`Retry-After` says until when) |
| Binance | HTTP 403 | Web application firewall block |
| Bybit | HTTP **403** | IP rate-limit ban (≈ 30 min) **or** a blocked country (e.g. the US) |
| OANDA | HTTP 401 | Token rejected — practice tokens only work on the practice host, live-account tokens on the live host |
| any | other 4xx, 3xx | The venue's message is reported; redirects are not followed |

## 15.4 Paging, pacing and retries

* **Windows.** `history` walks the range in windows of at most the venue's
  per-response maximum, never past the last closed minute. Venues with
  millisecond bounds (Binance, Bybit, Hyperliquid) get the last wanted candle's
  final millisecond (`open + 59 999`) as the end, which is complete and stops
  short of the next candle whether the venue reads it inclusively or not. Where
  the bound is a whole time and its reading is not documented (OANDA `to`,
  Coinbase `end`), the window is one minute shorter than the maximum and the
  bound is set one minute past it, with the same effect.
  Whatever a venue returns outside the requested window — the forming candle, a
  neighbour — is ignored, so newest-first ordering and end-bound semantics can
  neither duplicate nor drop bars. The pieces are merged by open time; the same minute delivered
  twice with different values is an error.
* **Budget.** Each provider paces itself with a token bucket well below the
  venue's published limit (table above). Binance responses carry
  `X-MBX-USED-WEIGHT-1M`; at 90 % of the IP's limit the provider pauses until
  the next minute.
* **Retries.** HTTP 429, any 5xx, network errors, and Bybit's in-band
  `retCode` 10006 (rate limit), 10000 and 10016 (server) are retried up to
  `max_retries` times with exponential backoff (`backoff_initial_s × 2^n`, capped
  at `backoff_max_s`), never sooner than a `Retry-After` header asks. A
  `Retry-After` above 300 s fails the call instead of stalling it.
* **Secrets.** The OANDA token is a `SecretStr`, sent only as an
  `Authorization` header and never logged or put in an error message; request
  URLs carry no secrets.

## 15.5 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KT_MARKETDATA__SOURCES_FILE` | `<config>/catalog/data_sources.yaml` | The data source map |
| `KT_MARKETDATA__DISABLED_PROVIDERS` | — | Providers this host must not use (comma-separated or a JSON list), e.g. geo-blocked venues |
| `KT_MARKETDATA__OANDA_TOKEN` / `_FILE` | — | OANDA API token (or a file holding it, e.g. a Docker secret). Without it, OANDA instruments fall back or are skipped |
| `KT_MARKETDATA__OANDA_ENVIRONMENT` | `practice` | `practice` (api-fxpractice.oanda.com) or `live` (api-fxtrade.oanda.com) — which host accepts the token. It selects where prices are **read**; it does not enable LIVE trading |
| `KT_MARKETDATA__CSV_DIR` | — | Directory of imported files `<INSTRUMENT>.csv` for the `csv` provider |
| `KT_MARKETDATA__BASE_URLS` | — | JSON object of per-provider `https://` base URL overrides (mirrors, test servers) |
| `KT_MARKETDATA__REQUEST_TIMEOUT_S` | 10 | Per-request timeout |
| `KT_MARKETDATA__MAX_RETRIES` | 5 | Retries after the first attempt |
| `KT_MARKETDATA__BACKOFF_INITIAL_S` / `_MAX_S` | 0.5 / 30 | Exponential backoff |
| `KT_MARKETDATA__CLOSE_DELAY_S` | 2 | Seconds after a minute ends before its bar counts as closed |

## 15.6 Building providers

```python
from kterminal.marketdata.factory import build_providers, load_data_sources

sources = load_data_sources(settings, catalog)
providers = build_providers(settings, sources, catalog)   # dict[str, MarketDataProvider]
providers["BTCUSD"]           # BinanceUsdmProvider (the same object as providers["NEARUSD"])
providers.skipped             # {"XAUUSD": "oanda needs an API token (…)", "MNQ": "csv needs …"}
providers.choices["BTCUSD"]   # SourceChoice: chain, chosen source, why others were passed over
await providers.aclose()      # closes each provider once
```

For each instrument the first usable source of its chain is chosen. One
provider object — one HTTP client, one request budget — serves every
instrument routed to that provider. Instruments with no usable source are left
out and listed in `skipped` with every reason; nothing is skipped silently.
`build_providers` refuses a map that does not fit the catalog and settings that
name unknown providers.

Live polling for paper trading calls `latest(instrument, since=<last open time
+ 1 min>)` once a minute (a few seconds after the minute, past
`close_delay_s`) and feeds the returned bars, in order, to the aggregator.
Warm-up uses `history`.

## 15.7 CSV import

`read_bars_csv(path, instrument, *, source, timeframe="1m", tz="UTC")` reads two
layouts:

* **Generic** — a header naming `time`, `open`, `high`, `low`, `close` and
  optionally `volume`, in any order and letter case (`timestamp`, `datetime`,
  `date`, `open_time` also name the time column; `vol` the volume). Other
  columns are ignored.
* **TradingView "Export chart data"** — `time,open,high,low,close`, then `Volume`
  when the chart shows volume, then one column per plotted series.

`read_tradingview_export(path, instrument=None, …)` reads only the TradingView
layout and also returns every plotted series per bar (`TradingViewExport.columns`,
`.extras`, `.series(name)`): repeated titles become `Plot`, `Plot (2)`, …; `NaN`
or empty cells are `None`. Without an instrument the bars are named after the
file up to its first comma (`OANDA_XAUUSD, 1.csv` → `OANDA_XAUUSD`), a label rather
than a canonical instrument. This is the input of the parity harness (doc 13,
P9). `write_bars_csv(path, bars)` writes the generic layout (ISO UTC times, exact
decimals, atomic replace) — what `kterminal data fetch` produces.

Rules (every error names the file and line):

* Times are unix seconds (TradingView's default), unix milliseconds or ISO 8601.
  ISO times with an offset or `Z` are exact; naive ISO times are read in `tz`
  and must be unambiguous there — a local time inside a DST change is refused
  rather than guessed. One file uses one time format.
* Rows must be strictly increasing (no duplicates, no overlaps), on whole
  minutes, and — for timeframes up to 1h — on the timeframe's UTC grid. Longer
  bars may be session-anchored (17:00 New York), so one step may be an hour
  short across a DST change. A file
  of 10+ rows in which no two consecutive bars are one timeframe apart (a 5m
  export read as 1m) is refused.
* OHLC must be consistent, prices present and finite, volume non-negative;
  empty or `NaN` volume reads as 0.
* Missing minutes stay missing.
* A TradingView export taken while the market is open ends with the bar still
  forming: export after the last wanted bar has closed, or drop that row. The
  `csv` provider drops it by time when serving the file.

## 15.8 Command line

```bash
kterminal data sources [--notes]
#   INSTRUMENT PROVIDER      SYMBOL           VOLUME    STATUS
#   XAUUSD     oanda         XAU_USD          tick      skipped: oanda needs an API token (…)
#   BTCUSD     binance_usdm  BTCUSDT          exchange  configured
#   …
#   Providers: binance_usdm configured — …, oanda oanda needs an API token …

kterminal data fetch BTCUSD --start 2026-10-01 --end 2026-10-02 --out btc_1m.csv
kterminal data fetch NEAR --start 2026-10-01T13:30-04:00 --end 2026-10-01T16:00-04:00 \
    --out near.csv --provider coinbase
```

`fetch` accepts any alias (`NEAR`, `MNQ1!`), reads times as UTC unless they
carry an offset, writes closed bars with `start <= time < end`, and reports the
count, the first and last bar and the source. It holds the whole range in memory
(about 0.4 GB for a year of 1m bars): fetch long histories a month at a time.
"configured" in `data sources` means usable on this host, not that the venue
was reached.

## 15.9 What was not verified live

The venue APIs are unreachable from the environment this layer was built in
(the egress proxy answers HTTP 403 for every market-data host), so **no
provider has been exercised against a live venue**. The providers are tested
against fake venues (`tests/fixtures/marketdata.py`) that reproduce each API's
documented response shapes, ordering, range semantics, forming candle, error
payloads and rate-limit signals. Sources:

* Binance — the official spot REST API documentation (klines, the
  startTime/endTime rule, 418/429/451, `X-MBX-USED-WEIGHT`); the USD-M
  endpoint's 1,500-row maximum and weight table are from memory of its
  documentation, not re-read;
* Bybit — the official v5 documentation (kline, rate limits, error codes);
* Hyperliquid — the official Python SDK and the ccxt implementation; the
  5,000-candle depth and the weight formula are from its documentation as
  remembered;
* OANDA — the official v20 Python SDK (parameters, `complete`, `volume`); the
  5,000-candle maximum and the request rate are from its documentation as
  remembered;
* Coinbase — the ccxt implementation (300 candles, `start`/`end`, row layout).

Not verified: the exact error texts (only their documented fields are parsed),
whether the end bounds are inclusive at Bybit, OANDA and Coinbase (the windowing
works either way), whether OANDA refuses a `to` that its own clock places in the
future (the host clock must be NTP-synchronised: `to` is never later than the last
closed minute, `close_delay_s` before this host's now), Hyperliquid's response to an unknown coin and to HIP-3
`dex:COIN` names, whether a USD-M kline request above 1,000 rows still weighs
10, the exact rate limits behind the budgets, how far back each venue's 1m history
reaches (other than Hyperliquid's documented 5,000 candles), which price component
TradingView's OANDA charts plot, and the columns of a real TradingView export
(the layout follows TradingView's documented "Export chart data" format).
Before the first forward test, run `kterminal data fetch` once per provider
from the deployment host and compare a few bars with the TradingView chart.
