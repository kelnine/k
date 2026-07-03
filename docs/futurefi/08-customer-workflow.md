# 08 — Customer Workflow

The customer lifecycle from first session to advocate, and what the product does at each
stage. North-star metric: **% of new customers who add an indicator to a live chart
within 48 hours** — everything in week one serves that number.

## Lifecycle stages

```
Visitor → Lead → Customer → Activated → Retained → Expanded → Advocate
```

| Stage | Definition | Owner surface | Key metric |
|-------|-----------|---------------|-----------|
| Lead | Email captured | /free, playground gate, newsletter | Lead → customer 90d % |
| Customer | First payment | Checkout | Time-to-purchase |
| Activated | TV access granted **and** indicator on chart | Success page + onboarding | 48h activation % |
| Retained | 2nd renewal / 60d active | Dashboard, community, updates | M2 retention |
| Expanded | 2nd product, bundle upgrade, or lifetime | Upsell surfaces | Expansion MRR |
| Advocate | Review, referral, or community contributor | Referrals, reviews, ideas | Referral % of revenue |

## Week-one journey (scripted)

| When | Touch | Content |
|------|-------|---------|
| T+0 | Success page | Set TV username → "access in ~5 min" → join Discord |
| T+5 min | Email "You're live" | TV link, 2-min setup video, docs link |
| T+0 in-app | Onboarding checklist | Link TV ✓ → Add to chart → Join Discord → Read quick-start (progress bar; completing unlocks a bonus preset pack) |
| T+48 h if not activated | Nudge email + in-app | Setup walkthrough, offer help in Discord |
| Day 3 | Email | 3 entry examples for their product |
| Day 7 | Email | Full strategy guide + journal pitch |
| Day 14 | Email + in-app | Review request (verified badge) |
| Day 21 | Email | "Pairs well with" cross-sell (only if activated) |

## Self-serve license portal (`/app/licenses`)

The flagship "no support ticket needed" surface:

- **Activate**: enter/confirm TradingView username → grant job → live status timeline
  (Queued → Processing → Granted) via Supabase Realtime — the user *watches* it complete.
- **Change TV username**: warns that old access is revoked; enforced 30-day cooldown
  (anti-sharing); triggers revoke+grant across all active entitlements.
- **Deactivate**: pause access without cancelling billing (e.g., account switch).
- **Transfer**: lifetime licenses only, once per 12 months, both parties confirm by
  email; new owner completes activation. Fully logged in `license_events`.

## Billing self-service (`/app/billing`)

Upgrade (prorated, instant), downgrade (at period end), switch interval, update card
(Stripe Elements), pause (up to 3 months), cancel (retention flow → period-end access),
invoice PDFs, crypto payment history with tx links. **Everything Stripe-portal-capable
is exposed in our UI** — customers never see a raw Stripe page except Checkout itself.

## Support journey

KB search first (deflection) → contextual "open a ticket" pre-filled with product +
plan + TV sync state → threaded ticket with email mirroring (reply by email works) →
resolution → 1–5 rating. SLA promise shown up front: 24 h weekdays, access issues
prioritized.

## Community & rewards loop

- Discord/Telegram roles sync from entitlements (bot checks on join + nightly).
- Trade ideas: post chart + thesis → votes → monthly leaderboard → prizes (free months,
  lifetime credit). Winners get a "Verified FF Trader" profile badge.
- Feature requests: submit → vote → public roadmap status → "shipped" email to voters.

## Expansion moments (where upsells appear — and only these)

1. Product page of an owned item → "Complete your suite, save 35%" banner.
2. Dashboard after 30 active days → annual/lifetime switch offer (savings math shown).
3. Scanner/Lex previews for unentitled users → blurred rows + unlock CTA.
4. Cancel flow → downgrade instead of churn.

No popups over the dashboard, no countdown-timer pressure inside the paid product —
premium brands don't nag their own customers.
