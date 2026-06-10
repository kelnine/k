# Signal Funnel — Business Model

A profitable rebuild of the "free crypto signals" Telegram channel in the
reference screenshot. The screenshot's channel gives signals away for free and
earns *only* from exchange referral links. We keep that, add a real data edge,
and stack a paid tier on top so the same content monetizes twice.

> Reality check: nobody gets rich *from the signals*. The signals are the
> content that fills the funnel. The money is in (1) exchange referral fee
> share and (2) recurring VIP subscriptions. This document is about the funnel,
> not about promising trading returns.

---

## Why the screenshot's channel is leaving money on the table

| Their setup | Problem | Our fix |
|---|---|---|
| Signals are 100% free | No recurring revenue, no upsell | Free tier is the teaser; VIP is paid |
| "Confidence: 37%" with no edge | Looks like noise, low trust | Confidence derived from real positioning/whale-bias data from the Co-Invest engine |
| Static exchange links | One-time referral, no attribution | Per-user referral codes + tracked deep links |
| Manual posting | Doesn't scale, irregular | Auto-generated on a schedule from the analysis engine |

---

## Revenue model — the funnel (chosen)

```
                 ┌─────────────────────────┐
   Ads / clips → │  FREE public channel     │  reach + social proof
                 │  3–5 teaser signals/day  │
                 └───────────┬─────────────┘
                             │ two parallel money paths
              ┌──────────────┴───────────────┐
              ▼                               ▼
   ┌───────────────────┐          ┌────────────────────────┐
   │ Exchange referral  │          │  VIP subscription       │
   │ links in footer    │          │  (Telegram Stars/crypto)│
   │ → % of trading fees│          │  → recurring MRR        │
   └───────────────────┘          └────────────────────────┘
```

### Path 1 — Exchange referral (zero-friction, like the screenshot)
- Every free post carries a referral footer (the engine already returns a
  `refCode`, e.g. `NMX8B0ND`).
- Exchanges pay **20–50% of taker/maker fees** of referred users, for life.
- Revenue = `referred_traders × avg_monthly_volume × fee_rate × your_share`.

### Path 2 — VIP subscription (the margin)
- Free tier intentionally withholds: exact entries on the *highest-confidence*
  setups, TP2/TP3, early posting, and position-sizing.
- VIP delivered via a private channel the bot gates on payment.
- Payment rails: **Telegram Stars** (native, no merchant account) and/or crypto.

---

## Unit economics (illustrative, not a promise)

Assume a modest channel after ramp:

| Lever | Conservative | Notes |
|---|---|---|
| Free subscribers | 10,000 | from clips/ads/SEO |
| → VIP conversion @ 2% | 200 VIP | typical for signal funnels |
| VIP price | $29/mo | mid-market |
| **VIP MRR** | **$5,800** | 200 × $29 |
| Referral: active traders | 500 | 5% of free base |
| Avg fee/trader/mo to you | $8 | volume × fee × share |
| **Referral revenue** | **$4,000** | 500 × $8 |
| **Total MRR** | **~$9,800** | |
| Infra cost | ~$20–50/mo | one small VM + bot |

The leverage is content cost ≈ 0 (auto-generated) against recurring revenue.

---

## Growth (top of funnel)

1. **Short-form clips** — auto-generate signal recaps as vertical videos
   (an image/video generation server is available in this workspace) → TikTok,
   Reels, Shorts, X.
2. **Public "track record" posts** — the bot logs every call and posts weekly
   win-rate so the channel builds verifiable credibility (the screenshot has none).
3. **Referral loop** — users who refer 3 friends get a week of VIP free.

---

## Compliance / staying alive (do not skip)

- **Not financial advice (NFA).** Every post carries the disclaimer. Never
  promise returns. Never imply guaranteed profit.
- **No custody.** The bot never touches user funds or API keys. It posts
  information; users trade on their own exchange accounts.
- **Disclose affiliation.** State that exchange links are referral links.
- **Jurisdiction.** Paid "investment advice" is regulated in many countries.
  We sell *access to research/education content*, not personalized advice —
  keep the framing general and disclaimed. Get local legal review before scaling
  paid tiers in the US/EU.
- **Platform ToS.** Respect Telegram and exchange affiliate terms.

---

## Build phases

- **Phase 1 (this repo):** bot that auto-generates, formats, and posts signals
  to a free channel, gates a VIP channel behind Telegram Stars, and tracks a
  public win/loss record. ← MVP
- **Phase 2:** auto-clip generation for social distribution; referral rewards.
- **Phase 3:** multi-exchange referral attribution dashboard; A/B post copy.
