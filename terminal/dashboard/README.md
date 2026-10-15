# K Terminal dashboard

The web terminal for watching the strategies paper trade: forward runtime and
data-feed health, the leaderboard of every forward account, account pages with
metrics, equity curve, positions, trades ("explain this trade") and signals,
per-instrument views, price charts with every strategy's trade markers, and the
kill switches. React 18 + TypeScript + Vite, no UI framework; the dark theme
follows the KCharts app at the repository root.

How it fits together, sign-in, roles, the API and deployment:
[docs/17-dashboard.md](../docs/17-dashboard.md).

![Overview](screenshots/02-overview.png)

## Development

Node 22. The API must be running (`kterminal api`, http://127.0.0.1:8000 by
default; `KT_API_URL` points elsewhere). The dev server and `vite preview`
proxy `/api` and `/health` to it, so the session cookie stays first-party as
behind Caddy.

```bash
npm ci
npm run dev          # http://127.0.0.1:5173
npm run typecheck    # tsc -b (strict)
npm test             # vitest: formatting, metrics, leaderboard, runtime health, chart data
npm run build        # type-check + production bundle in dist/
npm run preview      # serve dist/ on http://127.0.0.1:4173
```

For a local API over plain HTTP set `KT_AUTH__COOKIE_SECURE=false`, and create a
user first: `kterminal users add NAME --role ADMIN`.

## Layout

| Path | What |
|---|---|
| `src/api/` | `client.ts` (fetch with the session cookie and CSRF header), `types.ts` (the API's response shapes) |
| `src/pages/` | Login, Overview, Account, Instruments, Chart, Trades + Signals, System + Run |
| `src/components/` | Layout, leaderboard, tables, kill-switch button and dialog, trade "explain" drawer, equity curve, price chart, small UI parts |
| `src/lib/` | Pure helpers with unit tests: formatting, leaderboard sort/filter, runtime and feed health, kill-switch history, chart data; the 10-second polling hook; a minimal router |
| `src/kcharts/` | The KCharts canvas engine copied from the KCharts app in this repository (`src/engine`, `src/indicators`), extended (`trades.ts`, "K Terminal:" in `chart.ts`) with trade entry/exit markers and stop/target lines |

Production: `deploy/caddy/Dockerfile` builds this app and serves `dist/` from
Caddy (`/srv/dashboard`), with `/api` and `/health` proxied to the API.

## Screenshots

`screenshots/` holds the main pages. They were taken against the real forward
paper runtime fed by **synthetic** providers (`synthetic-fx`,
`synthetic-crypto`) — no live market data. To reproduce:

```bash
cd terminal/backend
createdb kt_dash_demo        # a database of its own (any way you like)
# users ada/otto/vera, a lab run, 8 h of forward trading by 16 demo instances,
# then the same session kept running live on the real clock (Ctrl-C stops it)
uv run python -m tests.dashboard_demo \
  --url postgresql://kterminal:kterminal@localhost:5432/kt_dash_demo --live &

KT_DATABASE__URL=postgresql://kterminal:kterminal@localhost:5432/kt_dash_demo \
KT_AUTH__COOKIE_SECURE=false uv run kterminal api &

cd ../dashboard && npm run build && npm run preview &
npm i --no-save playwright && npx playwright install chromium
KT_URL=http://127.0.0.1:4173 KT_USER=otto KT_PASSWORD=demo-password-123 node scripts/screenshots.mjs
```

The script fails when the browser logs an error (for example a
Content-Security-Policy violation), so it doubles as a smoke test.
