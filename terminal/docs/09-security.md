# 9. Security Design

## 9.1 Threat model

| # | Threat | Impact | Primary controls |
|---|---|---|---|
| T1 | Forged or replayed webhook | Unwanted trades | Per-strategy secret, IP allow-list, timestamp window, idempotency, risk engine |
| T2 | Theft of broker credentials | Account takeover / loss of funds | Credentials only in the `engine` container, Docker secrets, trade-only and IP-restricted API keys, never in TradingView/Telegram/logs |
| T3 | Dashboard compromise | Risk limits raised, LIVE enabled, kill switch abused | Not publicly exposed (VPN/Tailscale recommended), argon2id + TOTP, RBAC, re-auth for sensitive actions, audit log |
| T4 | Accidental LIVE trading | Real-money loss | Multi-key LIVE interlock (9.3), LIVE never default |
| T5 | Runaway strategy / bug | Rapid losses | Risk engine limits, max trades/day, kill switch (manual + automatic), daily-loss auto-flatten |
| T6 | Tampering with records | Loss of auditability | Append-only, hash-chained `audit_log`, least-privilege DB roles, off-site backups |
| T7 | Denial of service on the webhook | Missed signals | Caddy rate limits + body limits, IP allow-list, fast persist-and-ack path |
| T8 | Supply-chain compromise | Arbitrary code execution | Locked dependencies (`uv.lock`, `package-lock.json`), pinned image digests, `pip-audit`/`npm audit`, Dependabot, secret scanning |
| T9 | Secret leakage via logs/errors | Credential exposure | `SecretStr` everywhere, structured-log redaction processor, redacted exception context |

## 9.2 Controls by layer

**Network**
* Only Caddy publishes ports (80 → redirect, 443). Postgres, the API and the
  engine are on an internal Docker network with no published ports.
* Host firewall: allow 443/80, SSH restricted to known IPs or Tailscale only.
* `/api/v1/webhooks/tradingview` accepts only TradingView's source IPs
  (Caddy *and* application check). `/health/*` is not proxied publicly.
* Dashboard: recommended behind Tailscale / WireGuard or an identity-aware
  proxy (e.g. Cloudflare Access); never rely on obscurity.
* TLS 1.2+ with automatic certificates; HSTS; security headers
  (`Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`,
  `frame-ancestors 'none'`).

**Secrets**
* Development: `.env` (git-ignored). Production: Docker secrets mounted at
  `/run/secrets/<name>`, read by pydantic-settings; optional Vault/SOPS later.
* All secret settings are `SecretStr`: they print as `**********` in reprs,
  logs and `kterminal config show`.
* **Least privilege per process:** `api` gets DB + webhook config only;
  `engine` gets DB + broker credentials; `worker` gets DB + Telegram token.
* Broker API keys: trade-only scope (no withdrawals/transfers) and
  IP-restricted to the server wherever the broker supports it.
* Rotation procedures documented for each secret; webhook secrets support
  overlapping rotation.

**Application**
* Strict Pydantic validation (`extra="forbid"`) for every external input;
  request size limits; JSON-only APIs.
* Dashboard auth: argon2id passwords, TOTP 2FA, `HttpOnly; Secure;
  SameSite=Strict` session cookies, CSRF tokens, login rate-limiting/lockout.
* RBAC: `VIEWER` (read), `OPERATOR` (kill switch, pause strategies),
  `ADMIN` (risk profiles, accounts, LIVE enablement, users).
* Sensitive actions require re-authentication with TOTP within the last 5
  minutes: enabling LIVE, raising any risk limit, deactivating a kill switch,
  adding a broker account, rotating secrets.
* Constant-time comparison for all secrets/tokens.
* Errors returned to clients never include stack traces or internal details.

**Data**
* Separate DB roles: `kterminal_migrate` (DDL), `kterminal_app` (DML, no
  DDL, `INSERT/SELECT` only on `audit_log`), `kterminal_readonly` (reporting).
* Append-only, hash-chained audit log with a verification command.
* Encrypted off-site backups with tested restores.
* Broker account numbers masked in UI, logs and Telegram (`…1234`).

**Operations**
* Containers run as non-root with a read-only root filesystem,
  `no-new-privileges`, and dropped capabilities.
* NTP time sync (timestamp validation and session rules depend on it).
* Heartbeat / dead-man alert: if the engine heartbeat in `system_state`
  stops updating, the worker raises a critical Telegram alert.

## 9.3 LIVE trading safety interlocks

LIVE orders are possible only when **all** of the following are true. Each is
checked independently; any one missing → orders are rejected with
`LIVE_NOT_PERMITTED` and a critical alert is raised.

| # | Interlock | Where | Implemented |
|---|---|---|---|
| 1 | `KT_TRADING__DEFAULT_MODE` can never be `LIVE` (start-up error) | config | ✅ Phase 1 |
| 2 | Master switch `KT_TRADING__LIVE_ENABLED=true` | environment of the `engine` | ✅ Phase 1 |
| 3 | Acknowledgement phrase `KT_TRADING__LIVE_ACKNOWLEDGEMENT` matches exactly | environment | ✅ Phase 1 |
| 4 | Account `mode = LIVE`, set by an ADMIN with fresh 2FA (`live_enabled_by`) | database | Phase 10 |
| 5 | Strategy status `LIVE_APPROVED` (promotion gates met and signed off) | database | Phase 10 |
| 6 | Broker adapter declares live support and its configured endpoint is the live endpoint | adapter | Phase 10 |
| 7 | Account allocation explicitly enabled for that strategy | database | Phase 5 |

Turning LIVE **off** is always one step (any of the above), and is immediate.

## 9.4 Secure development lifecycle

* CI on every push: ruff, mypy `--strict`, import-linter architecture
  contracts, tests (including security-relevant tests: redaction, LIVE
  interlocks, webhook auth), Docker build.
* Secret scanning (gitleaks) and dependency audit in CI; `.env` files are
  git-ignored and `.env.example` contains no real values.
* Code review checklist for any change under `risk/`, `execution/` or
  `brokers/`; these paths can be protected with CODEOWNERS.
