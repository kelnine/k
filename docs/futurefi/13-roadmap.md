# 13 — Phased Development Roadmap

From first sale to platform company in five phases. Each phase has an exit criterion —
**do not start the next phase early**; the graveyard of indicator businesses is full of
half-built AI features on top of broken billing.

## Phase 0 — Foundation (Weeks 1–2)

Repo restructure to Turborepo (`packages/kcharts` extracted from `src/`), design tokens
+ base components, Supabase project + schema migration (doc 05), Stripe products/prices,
Vercel + Cloudflare + Resend + PostHog + Sentry wiring, CI (typecheck, lint, Lighthouse
budget).

## Phase 1 — MVP: Sell indicators properly (Weeks 3–8)

**Scope:** Home · catalog · 3 product pages (best products only) · pricing · checkout
(Stripe incl. Apple/Google Pay) · webhook projector + entitlements · TV sync queue +
license portal · customer dashboard (indicators, licenses, billing, settings) · auth ·
2 free indicators + email capture + drip · docs per product · legal pages · admin v1
(products, orders, customers, refunds, license queue) · support via email → tickets-lite.

**Explicitly cut:** playground, AI, community pages (Discord link only), affiliate
system (manual codes fine), PayPal/crypto, academy, scanner.

**Exit criteria:** first 50 paying customers · checkout→activation fully automated
(zero manual grants) · <5% of orders generate a support ticket · refund flow one-click.

## Phase 2 — Growth engine (Months 3–5)

Playground (KCharts + indicator ports — the differentiator) · full results/verified-
performance pages · blog + learning center + glossary net + SEO program (doc 11) ·
affiliate program + dashboard · PayPal + Coinbase Commerce · remaining product pages +
bundles · reviews system · newsletter (Resend Broadcasts) + launch-page machinery ·
Discord role-sync bot · admin v2 (content editor, newsletters, affiliate ops, analytics)
· support tickets full (KB + deflection) · Inngest job migration.

**Exit criteria:** $25k MRR · organic = 30%+ of new customers · affiliate = 15%+ ·
weekly content cadence sustained for 8 weeks.

## Phase 3 — AI & retention platform (Months 6–10)

**Lex v1** (chart upload → structured analysis, Claude vision + RAG over FF docs; free
tier 3/mo, paid tier in Suite+AI plan) · market scanner (productionize `bot/` signal
engine → `scanner_signals` → realtime table, teaser for unentitled) · trade journal +
AI weekly review · community v2 (ideas feed, feature requests + voting, leaderboards) ·
academy v1 (first course + quizzes + completion certificates) · strategy-builder presets
(Scalp/Swing/ICT/Gold/Crypto bundles of settings) · mobile-web polish pass.

**Exit criteria:** $60k MRR · AI tier attach rate 20%+ of new subs · M2 retention +10 pts
vs. Phase 1 baseline · support tickets/customer flat despite 3× customers.

## Phase 4 — Expansion (Months 10–18)

Marketplace v1 (third-party Pine devs sell through FF, 70/30 split — Stripe Connect,
review pipeline, per-seller storefronts) · copy-trading / signal automation research
(regulatory review FIRST) · prop-firm dashboard (multi-account tracking) · broker
integrations (read-only account sync for journal auto-fill) · mobile app (React Native
or PWA-first; push notifications for signals) · localization (ES/PT/DE first — trading
niches) · Lex v2 (multi-chart, strategy backtesting chat, portfolio awareness).

**Exit criteria:** $150k MRR · marketplace GMV meaningful (10+ sellers) · mobile DAU
20% of customer base.

## Phase 5 — Enterprise / platform (Month 18+)

AI portfolio manager + trading copilot (with compliance counsel) · automated trading
bridge (broker APIs, execution disclaimers/licensing per jurisdiction) · B2B: white-label
scanner/API for prop firms and communities · public API + developer program · SOC 2 if
B2B demands it · team plans.

## Sequencing logic (why this order)

1. **Billing + license automation before traffic** — every manual grant steals founder
   hours forever; automation compounds.
2. **Playground + results before ads** — they raise CVR, making every later visitor
   worth more.
3. **Content flywheel before AI** — SEO takes 6 months to pay; start the clock early.
4. **AI after retention surfaces exist** — Lex is a retention feature; it needs a
   dashboard people already visit.
5. **Marketplace last** — it monetizes an audience; build the audience first.

## Standing risks & mitigations

| Risk | Mitigation |
|------|-----------|
| TradingView changes invite-only mechanics | Adapter isolation (doc 09) + KCharts as long-term platform independence |
| Performance-claim regulation (YMYL/marketing) | Honesty-first results pages, counsel review of claims, disclaimers as first-class UI |
| Founder bus-factor on Pine scripts | Versioned script repo, documented build/publish runbook (admin doc 07) |
| Refund abuse on lifetime | 30-day guarantee w/ activity check; license_events evidence |
| AI cost blowout | Tiered rate limits, token budgets per plan, caching of common analyses |
