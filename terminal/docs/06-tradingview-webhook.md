# 6. TradingView Webhook Specification

## 6.1 TradingView constraints that shape the design

* Webhooks are only sent to **ports 80 and 443** → the endpoint sits behind
  Caddy on 443 with a valid certificate.
* TradingView **cannot add custom headers or sign requests** → authentication
  must be a shared secret inside the body. HMAC request signing is impossible.
* The body is the alert *message*; it is sent as `application/json` only when
  the message is valid JSON (otherwise `text/plain`).
* Requests that take more than ~3 seconds are cancelled, so the receiver must
  **persist and acknowledge**, never trade synchronously.
* Webhooks originate from a small set of published IP addresses (at the time
  of writing `52.89.214.238`, `34.212.75.30`, `54.218.53.128`,
  `52.32.178.7`). The list is configuration, not code — verify it against
  TradingView's documentation when deploying.
* TradingView requires 2-factor authentication on the account to use webhooks.

## 6.2 Endpoint

```
POST https://<your-domain>/api/v1/webhooks/tradingview
Content-Type: application/json            (text/plain is accepted and parsed as JSON)
Max body: 16 KiB
```

## 6.3 Payload (schema version 1)

```json
{
  "secret": "SERVER_SIDE_VALIDATED_SECRET",
  "strategy": "breakout_retest_tv",
  "symbol": "XAUUSD",
  "timeframe": "5",
  "action": "LONG",
  "price": 2678.40,
  "stop_loss": 2673.20,
  "take_profit": 2704.40,
  "timestamp": "2026-10-05T14:35:00Z",

  "bar_time": "2026-10-05T14:30:00Z",
  "risk": 0.5,
  "confidence": 0.8,
  "order_type": "MARKET",
  "alert_id": "optional-client-idempotency-key",
  "test": false,
  "metadata": { "level": 2676.9, "note": "retest of Asia high" }
}
```

| Field | Req. | Type | Validation / normalization |
|---|---|---|---|
| `secret` | ✔ | string | Constant-time compare against the strategy's active secret hashes (current + previous during rotation). Removed before the body is stored |
| `strategy` | ✔ | string | Must exist, be `enabled`, and be `EXTERNAL` (or explicitly webhook-enabled) |
| `symbol` | ✔ | string | `OANDA:XAUUSD`, `XAU_USD`, `xauusd` → canonical `XAUUSD` via `instrument_aliases`; must be an enabled instrument and in the strategy's `allowed_symbols` |
| `timeframe` | ✔ | string | TradingView `{{interval}}` values (`1`, `5`, `60`, `240`, `D`/`1D`, `W`/`1W`) or canonical (`5m`, `1h`) → canonical; must be in `allowed_timeframes` |
| `action` | ✔ | enum | `LONG` `SHORT` `EXIT_LONG` `EXIT_SHORT` `MOVE_SL` `NO_TRADE` (case-insensitive) |
| `price` | ✔ for entries | number | `> 0`; becomes `Signal.entry` |
| `stop_loss` | ✔ for `LONG`/`SHORT`/`MOVE_SL` | number | Side-consistent (see [05](05-strategy-interface.md#validation-rules-enforced-by-the-framework-before-anything-else-sees-the-signal)) |
| `take_profit` | — | number | Side-consistent |
| `timestamp` | ✔ | ISO-8601 or epoch ms | Alert fire time (`{{timenow}}`). Must be within **−60 s / +10 s** of server time (configurable) |
| `bar_time` | — | ISO-8601 or epoch ms | Bar time (`{{time}}`); used for idempotency and as `Signal.timestamp` |
| `risk` | — | number | `0 < risk ≤ 5`; still capped by the risk profile |
| `confidence` | — | number | `0 ≤ c ≤ 1` |
| `order_type` | — | enum | `MARKET` (default), `LIMIT`, `STOP` |
| `alert_id` | — | string ≤ 128 | Client idempotency key (overrides the derived key) |
| `test` | — | bool | Validate and record as `TEST`, never route to accounts — for setting up alerts |
| `metadata` | — | object ≤ 4 KiB | Stored verbatim |

Unknown top-level fields are rejected (`extra="forbid"`) so typos surface
immediately instead of being silently ignored.

## 6.4 Processing pipeline (target p99 < 250 ms)

| # | Check | Failure → HTTP | `reject_code` |
|---|---|---|---|
| 1 | Source IP in allow-list (Caddy **and** app; `X-Forwarded-For` trusted only from Caddy) | 403 | `IP_NOT_ALLOWED` |
| 2 | Rate limit (per IP 120/min, per strategy 30/min) | 429 | `RATE_LIMITED` |
| 3 | Body ≤ 16 KiB, parses as a JSON object | 413 / 400 | `TOO_LARGE` / `INVALID_JSON` |
| 4 | Schema valid (types, required fields, no extras) | 422 | `SCHEMA_INVALID` |
| 5 | Secret valid for that strategy | 401 (generic body, no detail) | `AUTH_FAILED` |
| 6 | Timestamp within window | 422 | `STALE_TIMESTAMP` / `FUTURE_TIMESTAMP` |
| 7 | Strategy exists/enabled/external | 422 | `UNKNOWN_STRATEGY` / `STRATEGY_DISABLED` |
| 8 | Symbol & timeframe known and allowed | 422 | `UNKNOWN_SYMBOL` / `SYMBOL_NOT_ALLOWED` / `TIMEFRAME_NOT_ALLOWED` |
| 9 | Signal semantics (SL/TP sides, required prices) | 422 | `INVALID_SIGNAL` |
| 10 | Idempotency key unseen | 200 `duplicate` | `DUPLICATE` |
| 11 | Semantic duplicate (cool-down) | 200 `duplicate` | `DUPLICATE_COOLDOWN` |
| 12 | One transaction: `webhook_events` + `signals` + `outbox('signal.received')` | 202 | — |

Every request — accepted or not — is written to `webhook_events` with the
secret stripped, the body hash, source IP, outcome and timing. Rejected
requests do not reveal which check failed beyond the status code for auth
failures. Repeated failures raise a (rate-limited, aggregated) *Webhook
failure* Telegram alert.

**Accepting a webhook is not approving a trade.** A kill switch or a risk
limit does not cause the webhook to be rejected — the signal is accepted,
recorded, and then rejected by the risk engine with a reason, so the audit
trail shows exactly what TradingView sent and why it did not trade.

### Idempotency vs. duplicate-signal protection

* **Idempotency** (exact replay): key = `alert_id` if supplied, otherwise
  `sha256(strategy | symbol | timeframe | action | bar_time)`; when
  `bar_time` is absent the alert `timestamp` truncated to the timeframe
  bucket is used. Enforced by a `UNIQUE` index on `signals.idempotency_key`, so
  it holds even across concurrent requests and multiple `api` replicas.
* **Duplicate protection** (semantic): at most one signal per
  `(strategy, symbol, timeframe, action)` per cool-down window (default: one
  bar). Catches two alerts accidentally configured for the same condition or
  `alert.freq_all` firing repeatedly within a bar.

## 6.5 Responses

```json
202 {"status": "accepted",  "signal_id": "0192…", "correlation_id": "0192…"}
200 {"status": "duplicate", "signal_id": "0192…"}
200 {"status": "test_ok"}
4xx {"status": "rejected",  "code": "SCHEMA_INVALID", "detail": "stop_loss must be below price for LONG"}
401 {"status": "rejected",  "code": "AUTH_FAILED"}
```

## 6.6 Secrets: what goes in an alert, and what never does

* The alert contains **only the webhook secret** — a random 256-bit token
  that can do exactly one thing: submit a signal for one strategy, which the
  risk engine still evaluates. It cannot read data, change settings, or reach
  a broker.
* **Broker credentials, API keys and account numbers never appear in
  TradingView** — they exist only in the `engine` container's secrets.
* Secrets are stored hashed (SHA-256 of a high-entropy token; compared in
  constant time), are per strategy, and support rotation: a new secret is
  issued, both are valid until the old one's `expires_at`, then the old hash
  is removed. `kterminal webhook rotate-secret <strategy>` prints the new
  secret once.

## 6.7 Alert message templates

**A. Pine *strategy* (recommended).** Build the variable part per order in
Pine with `alert_message=` and keep the secret only in the alert dialog:

```pine
//@version=6
strategy("Breakout + Retest", overlay=true)
// …
if longCondition
    strategy.entry("L", strategy.long,
         alert_message='"action":"LONG","price":' + str.tostring(close) +
                       ',"stop_loss":' + str.tostring(sl) + ',"take_profit":' + str.tostring(tp))
    strategy.exit("L-exit", "L", stop=sl, limit=tp,
         alert_message='"action":"EXIT_LONG","price":' + str.tostring(close))
```

Alert dialog → *Message* (the secret is typed here, not in code):

```
{"secret":"<paste>","strategy":"breakout_retest_tv","symbol":"{{ticker}}","timeframe":"{{interval}}","timestamp":"{{timenow}}","bar_time":"{{time}}",{{strategy.order.alert_message}}}
```

**B. Pine *indicator* with `alertcondition()`.** Plot SL/TP with
`display=display.none` and reference them by name:

```
{"secret":"<paste>","strategy":"my_indicator_tv","symbol":"{{ticker}}","timeframe":"{{interval}}","action":"LONG","price":{{close}},"stop_loss":{{plot("SL")}},"take_profit":{{plot("TP")}},"timestamp":"{{timenow}}","bar_time":"{{time}}"}
```

**C. Pine indicator with `alert()`.** The message is built entirely in code,
so the secret must come from an `input.string(..., display=display.none)`.
Supported, but A or B is preferred because the secret then never lives in the
script's inputs.

## 6.8 Testing the endpoint

```bash
curl -sS https://<domain>/api/v1/webhooks/tradingview \
  -H 'Content-Type: application/json' \
  -d '{"secret":"…","strategy":"breakout_retest_tv","symbol":"XAUUSD","timeframe":"5",
       "action":"LONG","price":2678.40,"stop_loss":2673.20,"take_profit":2704.40,
       "timestamp":"'"$(date -u +%FT%TZ)"'","test":true}'
```

The IP allow-list can be bypassed for `test: true` requests only from
operator IPs listed in `KT_WEBHOOK__OPERATOR_IPS`.
