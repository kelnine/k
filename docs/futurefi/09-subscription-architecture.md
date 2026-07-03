# 09 — Subscription & Billing Architecture

## The one rule

**Stripe owns billing truth. The `entitlements` table owns access truth. Webhooks and
jobs are the only bridge between them.** The app never asks "does this user have an
active Stripe subscription?" — it asks "is there an active entitlement row?" This makes
lifetime licenses, crypto payments, free grants, comps, and future providers all
identical to the app: they're just entitlement rows with different `source` values.

```
┌────────────┐   webhooks   ┌───────────────┐   jobs    ┌──────────────────┐
│  Stripe    ├─────────────▶│               │──────────▶│ TradingView       │
│  PayPal    ├─────────────▶│  Billing      │  grant/   │ invite-only access│
│  Coinbase  ├─────────────▶│  projector    │  revoke   └──────────────────┘
└────────────┘              │  (webhook     │──────────▶ Discord/Telegram roles
                            │   handlers)   │──────────▶ Resend emails
                            └──────┬────────┘
                                   ▼
                     orders · subscriptions · entitlements   ◀── app reads only this
```

## Product ↔ Stripe mapping

- Every FF product/interval → one Stripe **Price** (`prices.stripe_price_id`).
- Monthly/annual → Stripe **Subscriptions**. Lifetime → one-time **Payment Intents**.
- Bundles are single Stripe Prices; on payment the projector **fans out entitlements to
  every product in the bundle** (`bundle_items`). Selling the bundle as one price keeps
  Stripe simple; fan-out keeps access granular.
- Coupons/student discounts → Stripe Coupons + Promotion Codes, mirrored in `coupons`
  for our own analytics and gating (student codes require .edu / SheerID check first).
- Tax: **Stripe Tax** from day one (EU VAT / UK / US sales tax on SaaS is real).

## Checkout paths

| Method | Implementation |
|--------|----------------|
| Card, Apple Pay, Google Pay | Stripe Checkout (hosted) at MVP → embedded Elements later. Apple/Google Pay are free with Checkout — just enable. |
| PayPal | PayPal JS SDK order flow → capture → our webhook handler. (Alternative: run everything through Paddle/LemonSqueezy as merchant-of-record — simpler tax, higher fees. Decision: Stripe+Tax for margin, revisit if EU volume dominates.) |
| Crypto (BTC/ETH/SOL/USDC) | Coinbase Commerce hosted charge → `charge:confirmed` webhook. Crypto = **lifetime & annual only** (no recurring pull). Price locked 15 min; under/overpayment handled by Commerce. |

## Webhook projector (the critical service)

`/api/webhooks/{stripe|paypal|coinbase}` — verify signature → insert into
`webhook_events` (id = provider event id; **unique constraint = idempotency**) → process
→ mark `processed_at`. Failures leave `error` set; a cron retries unprocessed events.
Handlers are pure functions of (event, db) — replayable, testable.

| Event | Projection |
|-------|-----------|
| `checkout.session.completed` | Create/attach user (email match or new) → `orders(paid)` → entitlements (fan-out) → TV grant jobs → commission (pending) → receipt |
| `invoice.paid` (renewal) | Extend `subscriptions.current_period_end` → extend entitlement `expires_at` |
| `invoice.payment_failed` | Status `past_due`; **entitlements stay active during dunning** (Stripe Smart Retries, ~14 d) — never punish a card hiccup with instant revoke |
| `customer.subscription.updated` | Mirror status/cancel_at_period_end/plan changes; prorations follow Stripe's math |
| `customer.subscription.deleted` | Expire entitlements → TV revoke jobs → Discord role strip → winback sequence |
| `charge.refunded` | Order refund state → commission reversal → optional revoke |
| `charge.dispute.created` | Flag + admin alert + evidence pack draft |

**Grace periods:** entitlement expiry = `current_period_end + 3 days` (webhook lag
buffer); revoke jobs run only after true expiry. Downgrades apply at period end;
upgrades instantly with proration.

## TradingView access sync (the domain-specific hard part)

TradingView has **no official API for invite-only script access**, so this is an
isolated, replaceable adapter — never inline in webhooks:

- `tv_access_jobs` queue (schema doc 05): `grant`/`revoke` + username + script id.
- Worker (Vercel cron every minute at MVP → QStash/Inngest later) processes jobs via a
  headless-session adapter with conservative rate limits, exponential backoff, max 5
  attempts, then alerts admin. All state transitions visible to the customer
  (Queued → Processing → Granted) and to admins (retry buttons).
- **Buffer promise:** marketing says "access within minutes", never "instant".
- If TradingView ever ships an official mechanism, only the adapter changes.
- Nightly reconciliation: diff expected access (active entitlements) vs. recorded grants;
  auto-heal drift; report anomalies (leak detection = revenue protection).

## Plan matrix (launch)

| Plan | Monthly | Annual (−20%) | Lifetime |
|------|---------|---------------|----------|
| Single indicator | $49–99 | $470–950 | $990–1,490 |
| Complete Suite (7 + scanner) | $149 | $1,430 | $2,990 |
| Suite + AI (Lex) — Phase 3 | $199 | $1,910 | — (AI costs recur) |

Lifetime terms in writing: lifetime of the *product*, includes updates, excludes future
*separate* products; transferable once/12 mo. Lifetime revenue recognized but treat ~15%
as support liability in planning.

## Entitlement checks in the app

```ts
// Single source of truth, cached per request:
const access = await getEntitlements(userId);       // reads active_entitlements view
access.has('smart-money-pro')                        // product gate
access.hasAny(['suite'])                             // tier gate
// Edge middleware guards /app/scanner, /app/lex; server actions re-check (never trust UI)
```

## Failure-mode playbook

| Failure | Design answer |
|---------|---------------|
| Webhook missed | Idempotent replay + hourly reconciliation cron against Stripe API |
| Double-fire | `webhook_events` PK dedupe |
| TV grant fails repeatedly | Admin alert queue + customer status honesty + manual fallback |
| Chargeback | Evidence pack from `license_events` (delivery + usage proof) |
| Card fails on renewal | Dunning: Stripe retries + our day 3/7/12 emails; access holds 14 d |
| Crypto underpaid | Coinbase Commerce resolution flow; entitlement only on `confirmed` |
