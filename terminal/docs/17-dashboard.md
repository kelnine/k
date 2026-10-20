# 17. Dashboard

The dashboard is the terminal you look at: a web page for watching the
strategies paper trade. It shows whether the forward runtime is alive, the
health of every data feed, a leaderboard of all forward accounts, each
account's metrics, equity curve, positions, trades (with "explain this trade")
and signals, price charts with every strategy's trade markers, and the kill
switches. It reads what the forward runtime ([12.7](12-strategy-lab.md#127-forward-sessions-the-lab-on-live-data))
and the lab record in PostgreSQL; the only thing it changes is the kill-switch
table (and the users' own sessions). LIVE trading does not exist here either:
there is no endpoint that places an order or changes an account's mode.

| Part | Where | What |
|---|---|---|
| Single-page app | `terminal/dashboard` (React 18, TypeScript, Vite) | The pages; polls the API every 10 s (no WebSocket yet) |
| Dashboard API | `kterminal.api` (`/api/v1`, `api` process) | JSON read models, sign-in, kill switches; serves no static files |
| Edge proxy | `deploy/caddy` (Caddy) | HTTPS, security headers, the SPA's files, `/api/*` to the API (`/health/*` stays internal); listens on 127.0.0.1 unless `KT_BIND_ADDRESS` is set |

Screenshots of every page are in [`terminal/dashboard/screenshots/`](../dashboard/screenshots/)
(demo data from synthetic providers; see [the dashboard README](../dashboard/README.md)).

## 17.1 First start

With the Docker stack ([16](16-running-paper-trading.md), `deploy/docker-compose.yml`):

```bash
cd terminal
make up          # secrets, then the API image and the Caddy image (with the dashboard)
                 # (or start.sh / start.ps1: docs/18-quick-start.md)
```

Then open `https://localhost/` (Caddy's local CA). The Docker stack publishes
the dashboard on this computer only and opens it **without sign-in**
([17.3](#173-sign-in-and-sessions)). On a server, with
`KT_BIND_ADDRESS=0.0.0.0`, `KT_PUBLIC_DOMAIN` and `KT_LOCAL_NO_LOGIN=false` in
`terminal/.env`, create a user and sign in:

```bash
docker compose --project-directory deploy -f deploy/docker-compose.yml \
  exec api kterminal users add ada --role ADMIN   # asks for the password twice
```

Until a forward session runs the
overview says **No forward session yet**; it turns green when the runtime
(`kterminal paper start`, or the `engine` service) writes its first status.

Without Docker, from `terminal/` (PostgreSQL running, schema migrated):

```bash
uv run --project backend kterminal users add ada --role ADMIN
KT_AUTH__COOKIE_SECURE=false KT_AUTH__SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))") \
  uv run --project backend kterminal api              # http://127.0.0.1:8000
cd dashboard && npm ci && npm run dev                 # http://127.0.0.1:5173, proxies /api and /health
```

`KT_AUTH__COOKIE_SECURE=false` is for plain `http://127.0.0.1` only; the API
refuses to start with it in `production`.

## 17.2 Users and roles

Users live in the `users` table (argon2id password hashes). They are managed
from the command line on the server; every change is written to the audit log.

| Command | Does |
|---|---|
| `kterminal users add NAME --role VIEWER\|OPERATOR\|ADMIN` | Creates a user; the password is asked for twice, never echoed. Names: 3–32 characters, a letter first, then `a-z 0-9 . _ -` (stored lower-case) |
| `kterminal users list` | Every user with role, state and creation time |
| `kterminal users disable NAME` / `enable NAME` | A disabled user cannot sign in; their open sessions end on their next request |
| `kterminal users set-password NAME` | New password (asked twice); sessions opened with the old one end |

A password must have at least `KT_AUTH__PASSWORD_MIN_LENGTH` (12) characters,
at least 5 different characters, no leading or trailing whitespace, and must
not contain the user name.

| Role | Can |
|---|---|
| `VIEWER` | Read every page |
| `OPERATOR` | Also activate and release kill switches |
| `ADMIN` | Everything an operator can (user management stays on the command line for now) |

## 17.3 Sign-in and sessions

**Without sign-in (this computer only).** `KT_AUTH__LOCAL_NO_LOGIN=true` (the
Docker stack's default, `KT_LOCAL_NO_LOGIN` in `terminal/.env`) opens the
dashboard without a login: the page asks `GET /api/v1/auth/options`, then
`POST /api/v1/auth/local` opens an ordinary session for the built-in user
`local` (ADMIN, created on first use with a random password nobody knows), so
cookies, CSRF tokens, roles and the audit log work as below, and an expired
session is simply opened again. It is accepted only while the dashboard is
published on a loopback address: the API refuses to start when
`KT_AUTH__PUBLISHED_ADDRESS` (compose passes `KT_BIND_ADDRESS`, default
`127.0.0.1`) is anything else, and `/auth/local` answers only requests
addressed to `localhost` or a loopback address (`403 LOCAL_ONLY` otherwise; a
DNS-rebound name gets nothing). Anyone who can use this computer's browser can
use the dashboard: what it guards is paper trading, never real money or the
OANDA token (which the dashboard never shows). Password users still work
alongside; `kterminal users list` starts with `sign-in: off` in this mode.

* **Password check:** argon2id (argon2-cffi's RFC 9106 parameters). An unknown
  user name costs the same time as a wrong password. Hashes made with older
  parameters are re-hashed at the next successful sign-in.
* **Session:** a signed token in the cookie `kt_session` —
  `HttpOnly; SameSite=Strict; Secure; Path=/`, lifetime
  `KT_AUTH__SESSION_TTL_MINUTES` (12 h), then sign in again. The token holds the
  user id, a random session id, issue and expiry times and a tag of the
  password hash, signed with HMAC-SHA256. Every request re-reads the user, so
  disabling a user, changing the password or signing out takes effect at once.
  Signing out records the session id as revoked (`system_state`
  `auth.revoked_sessions`) until it would have expired anyway.
* **CSRF:** `POST`/`PUT`/`PATCH`/`DELETE` requests must carry
  `X-CSRF-Token`: HMAC of the session id, returned by sign-in and
  `GET /api/v1/auth/me`. A cross-site page can neither read nor compute it, and
  `SameSite=Strict` keeps the cookie off cross-site requests in the first place.
* **Rate limiting:** `KT_AUTH__MAX_FAILED_LOGINS` (5) failures for a user name
  within `KT_AUTH__LOCKOUT_MINUTES` (15) lock that name for the rest of the
  window (`429` with `Retry-After`, whether or not the name exists);
  `KT_AUTH__MAX_FAILED_LOGINS_PER_IP` (30) failures from one address block the
  address. The counters live in the API process (one replica). A lockout is
  audited (`auth.lockout`); so are sign-in and sign-out (`auth.login`,
  `auth.logout`).
* **Secret:** `KT_AUTH__SESSION_SECRET` (≥ 32 characters) or
  `KT_AUTH__SESSION_SECRET_FILE` (Docker secret `session_secret`) signs sessions
  and CSRF tokens. Without it the API makes a random one at start-up: secure,
  but every restart signs everyone out.
* **Errors** have one shape: `{"status": "error", "code": "...", "message": "...", "correlation_id": "..."}`
  (`NOT_AUTHENTICATED` 401, `INVALID_CREDENTIALS` 401, `LOGIN_LOCKED` 429,
  `CSRF_TOKEN_INVALID` 403, `FORBIDDEN` 403, `REAUTH_REQUIRED` 403, `LOCAL_ONLY` 403,
  `NOT_FOUND` 404).
  Every API response is `Cache-Control: no-store`.

Caddy adds HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, a `Content-Security-Policy` that allows only the
dashboard's own scripts, styles, images and API (`default-src 'none'`), and
`Cross-Origin-Opener-Policy`. TOTP second factors ([9.2](09-security.md#92-controls-by-layer))
are not implemented yet; until they are, keep the dashboard off the public
internet (VPN, Tailscale or an identity-aware proxy in front of Caddy).

## 17.4 Pages

| Page | Shows |
|---|---|
| Overview | Runtime status (running / warming up / stopped / error with its reason / silent when no update for 2 min), session, last processed minute; totals of the forward accounts; the kill switches (global button, active switches, what the runtime last applied); data feeds per instrument (provider, `ok`/`stale`/`closed`/`no_provider`, last bar, lag, last error — problems first); the leaderboard |
| Leaderboard | Every forward account (one per instance): strategy id, definition, instruments, timeframe, parameters, trades (flagged *low n* below 30), win rate, profit factor, average R, expectancy, net P&L, return, max drawdown, open positions, runtime state or *halted*. Sortable by every column (default: average R, ties by profit factor — appendix A's ranking), filterable by strategy, instrument and timeframe, with a free-text search over ids, names, instruments and parameters |
| Account | Strategy, parameters, timeframe and context timeframes, instruments, version hash, account settings; all metrics; equity curve (equity, balance, start); open positions marked at the latest stored close; trades with **Explain**; signals with outcome and reject code; the instrument chart with this account's trades; *Halt account* / *Halt strategy* |
| Explain (drawer) | One trade end to end ([4.9](04-database-schema.md#49-the-audit-trail-explaining-a-trade)): result and costs, why it entered (the signal and the market data the strategy saw), the risk decision with every rule's verdict and values, orders and fills, stop and target changes, why it exited, ledger entries, the strategy version and account settings in force |
| Instruments | Per instrument: name, the forward instances trading it, timeframes, open positions, feed state, newest stored candle; the detail page lists its open positions and the leaderboard of its accounts |
| Chart | Pick instrument and timeframe (1m, 5m, 15m, 30m, 1h, 4h): candles from `candles` with every strategy's trades (filter by instance; forward, lab-run or all accounts) — entry ▲/▼, exit ● (green win, red loss), stop and target lines of open or selected trades; clicking a marker explains the trade. Drag, wheel-zoom and the KCharts indicators work as in KCharts |
| Trades | Every trade, filterable by accounts (forward / lab runs / all), status, side, strategy and instrument |
| Signals | Every signal with its outcome — `APPROVED`, `REJECTED` (first failing risk rule, e.g. `KILL_SWITCH_ACTIVE`), `INVALID` (refused by the framework, with why), `IGNORED`, `NO_DECISION` (exits, stop moves) |
| System | Instances (versions, parameters, enabled, runtime state and faults, per-strategy kill switch), runs (forward sessions and lab simulations; a run's page lists its accounts), recorded faults, the kill-switch history (changes and when a session applied them), and the raw runtime status document |

Empty states say what to do: no users (`kterminal users add`), no forward
session (`kterminal paper start`), no accounts (`kterminal lab provision`).
The layout works down to phone width; wide tables scroll sideways with the
strategy column pinned.

## 17.5 Metrics

Every number is computed from what was recorded — closed trades, the ledger and
equity snapshots — with the definitions of [appendix A](appendix-a-metrics.md),
never stored or hard-coded. Trade statistics use
`kterminal.analytics.summary.summarize_trades`, the function the lab report
uses; `kterminal.api.metrics` adds the account-level ones:

| Metric | Definition |
|---|---|
| Balance | `balance_after` of the account's newest ledger entry (the starting balance before any) |
| Equity | The balance while flat; with open positions the newest equity snapshot (its open P&L added to the balance when the ledger has moved since) |
| Return % | `(equity − starting balance) / starting balance × 100` |
| Net P&L | Sum of closed trades' `net_pnl` (after commission, spread, swap and funding) |
| Win rate, profit factor, average R | Appendix A; profit factor is empty without losing trades |
| Expectancy | `win rate × average winner + (1 − win rate) × average loser` (currency); in R it is the average R |
| Max drawdown | Largest peak-to-trough fall of the equity curve, the starting balance counting as the first peak, in currency and % of the peak |
| Open position P&L | `(last close − entry) × qty × value per unit` (sign by side), the value per unit recovered from the trade's own `initial_risk`; before exit costs |

A whole leaderboard costs a fixed handful of queries however many accounts it
has (drawdowns are computed with window functions in PostgreSQL).

## 17.6 Kill switches from the dashboard

Operators and admins use the *Halt* buttons: **Halt all trading** (global), per
account, per strategy instance. Activating needs a reason (3–500 characters)
and may close the covered positions; releasing a switch re-enables trading, so
it needs the operator's password again (the built-in `local` user of a
dashboard without sign-in has none: its explicit release with a reason is the
confirmation). The change goes through the same code
as `kterminal killswitch on/off` (`kterminal.db.repositories.kill_switches`):
the `kill_switches` row and a `killswitch.activate` / `killswitch.deactivate`
audit entry (actor `user:<user id>`) in one transaction. The runtime reads the
table before every minute, so a change takes effect in the next batch; the
overview shows what the runtime last applied, and the history lists the
`killswitch.applied` entries a session wrote. What a switch does to entries,
resting orders and open positions is in [12.7](12-strategy-lab.md#kill-switches).

## 17.7 API

All under `/api/v1`, JSON, typed by the Pydantic models in
`kterminal/api/schemas.py`. Money, prices and quantities are decimal strings;
times are UTC ISO-8601. Lists that grow without bound are pages:
`{items, total, limit, offset}` (`limit` ≤ 500). Every route except sign-in
needs a session; state-changing ones also the CSRF token. Outside production
the OpenAPI schema is at `/api/v1/openapi.json` and interactive docs at
`/api/v1/docs` (`KT_API__DOCS_ENABLED`, on by default; never in production).

| Method and path | Role | Returns |
|---|---|---|
| `POST /auth/login` | — | `{user, csrf_token, expires_at}` and the session cookie |
| `POST /auth/logout` | any | 204; the session is revoked |
| `GET /auth/me` | any | The signed-in user and the CSRF token |
| `GET /overview` | any | Runtime view, global halt, active kill switches, forward totals, recent runs, faults in 24 h |
| `GET /system/runtime` | any | `{present, stale, age_seconds, stale_after_seconds, status, error}`; `status` is the runtime's document ([12.7](12-strategy-lab.md#runtime-status-system_statepaperruntime)) |
| `GET /system/info` | any | Version, environment, default mode, whether the global LIVE interlocks are set (no LIVE execution exists either way) |
| `GET /system/faults` | any | Page of recorded faults (`instance_id`, `run_id`) |
| `GET /accounts` | any | Page of accounts with metrics: `scope=forward\|run\|all`, `run_id`, `instance_id`, `strategy`, `instrument`, `timeframe`, `status`, `q`, `sort`, `order` |
| `GET /accounts/{id}` | any | One account with its settings version, high-water mark and the switches covering it |
| `GET /accounts/{id}/equity` | any | Equity curve, downsampled to `max_points` (1500) |
| `GET /positions` | any | Open trades marked at the latest stored close (`scope`, `account_id`, `instance_id`, `instrument`, `run_id`) |
| `GET /trades` | any | Page of trades (`scope`, `account_id`, `instance_id`, `run_id`, `instrument`, `status`, `direction`, `since`, `until`) |
| `GET /trades/{id}` | any | "Explain this trade" |
| `GET /signals` | any | Page of signals with decision and outcome (`scope`, `account_id`, `instance_id`, `run_id`, `instrument`, `action`, `outcome`, `since`, `until`) |
| `GET /candles` | any | `instrument`, `timeframe`, `source`, `until`, `limit` (≤ 5000), `markers=forward\|run\|all\|none`, `account_id`, `run_id`, `instance` (repeatable) |
| `GET /instruments`, `GET /instruments/{symbol}` | any | Per-instrument summary; detail with accounts and open positions |
| `GET /instances`, `GET /instances/{id}` | any | Instances with current version, version history, dedicated account and runtime state |
| `GET /runs`, `GET /runs/{id}` | any | Lab and forward runs with counts (`kind`, `status`) |
| `GET /kill-switches` | any | Every switch and the latest 50 history entries |
| `POST /kill-switches` | OPERATOR | `{scope, scope_id, active, reason, close_positions, password}` (password only to release) |

**Candles** come from the `candles` table. A stored timeframe is returned as
is; any other is aggregated in SQL (`date_bin`, buckets aligned to UTC
midnight like the lab's aggregator) from the coarsest stored timeframe that
divides it. The source is the one with the newest bar unless `source` names
another. Buckets only partly covered (the forming bar, gaps) are built from
the bars that exist; gaps are never filled.

## 17.8 Deployment

`deploy/caddy/Dockerfile` builds the image in two stages: `node:22-alpine`
runs `npm ci` and `npm run build` (type-check + Vite bundle), then
`caddy:2-alpine` gets the Caddyfile and the bundle in `/srv/dashboard`. Build
context is `terminal/`; `Dockerfile.dockerignore` sends only the dashboard
sources and the Caddyfile. In the Caddyfile, `/api/*` goes to `api:8000`,
`/health/*` answers 404 (the probes are for the container health checks only),
the TradingView webhook path keeps its IP allow-list, and every
other path is a file of the bundle or — for client-side routes —
`index.html`. Hashed assets are cached for a year, `index.html` never.

Compose publishes Caddy's ports on `127.0.0.1` only, so the dashboard opens on
the computer that runs it and nowhere else. On a server with a domain, set
`KT_PUBLIC_DOMAIN` and `KT_BIND_ADDRESS=0.0.0.0` in `terminal/.env`.

CI (`.github/workflows/terminal-ci.yml`, job `dashboard`) runs `npm ci`, the
type-check, the unit tests (vitest), the production build, builds the Caddy
image and validates its configuration.

## 17.9 Known limits

* No TOTP and no in-browser user management yet; users are managed with the CLI.
* Updates are polled every 10 s; WebSocket push comes later.
* Sign-in rate limits are per API process (the stack runs one).
* The chart shows intraday timeframes only (daily bars need each instrument's
  session boundaries).
* The dashboard has been exercised end to end against the real forward runtime
  with synthetic market data only; live provider data could not be reached
  from the build environment.
