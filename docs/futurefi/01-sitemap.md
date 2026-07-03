# 01 — Sitemap

Three zones: **Public** (marketing + SEO surface), **App** (authenticated customer
dashboard), **Admin** (staff only). URLs are designed for SEO longevity — product and
content slugs never encode pricing or versions.

```
futurefi.io
│
├── /                                  Home
├── /indicators                        Indicator catalog (filterable grid)
│   ├── /indicators/sniper-pro         FutureFi Sniper Pro
│   ├── /indicators/pa-suite           FutureFi PA Suite
│   ├── /indicators/smart-money-pro    FutureFi Smart Money Pro
│   ├── /indicators/breakout-ai        FutureFi Breakout AI
│   ├── /indicators/scalper            FutureFi Scalper
│   ├── /indicators/swing-pro          FutureFi Swing Pro
│   ├── /indicators/dashboard          FutureFi Dashboard
│   └── /indicators/[slug]/docs        Per-product documentation (versioned)
│       └── /indicators/[slug]/changelog
├── /bundles                           Bundle catalog
│   └── /bundles/[slug]                e.g. /bundles/complete-suite, /bundles/ict-pack
├── /free                              Free indicators (email-gated downloads)
│   └── /free/[slug]
├── /playground                        Interactive chart playground (KCharts engine)
│   └── /playground/[indicator-slug]   Deep-link with an indicator pre-loaded
├── /pricing                           Plans: monthly / annual / lifetime / bundles
├── /results                           Performance tracker: backtests + disclaimers
│   └── /results/[indicator-slug]
├── /scanner                           Live market scanner (teaser public, full = paid)
│
├── /learn                             Learning Center hub
│   ├── /learn/guides                  Trading guides (evergreen SEO)
│   │   └── /learn/guides/[slug]
│   ├── /learn/tutorials               Video tutorials
│   │   └── /learn/tutorials/[slug]
│   ├── /learn/strategies              Strategy explanations
│   │   └── /learn/strategies/[slug]
│   ├── /learn/glossary                Trading terms (SEO net: /learn/glossary/[term])
│   └── /learn/faq                     Global FAQ
├── /blog                              Blog + market updates
│   ├── /blog/[slug]
│   └── /blog/category/[category]      e.g. smart-money-concepts, scalping, gold
├── /academy                           Courses & certifications (Phase 3)
│   └── /academy/[course-slug]
│
├── /ai                                AI hub — Lex & the AI suite
│   ├── /ai/lex                        AI Copilot: chart upload → trade ideas
│   ├── /ai/scanner                    AI market scanner
│   ├── /ai/journal                    AI trade journal
│   └── /ai/risk                       AI risk management
│
├── /community                         Community hub
│   ├── /community/leaderboard         Trader leaderboards
│   ├── /community/ideas               Customer trade ideas feed
│   ├── /community/requests            Feature requests + voting
│   ├── /discord  → redirect           Invite deep-link (tracked)
│   └── /telegram → redirect           Invite deep-link (tracked)
│
├── /affiliates                        Affiliate program landing
├── /ambassadors                       Ambassador program landing
├── /newsletter                        Newsletter signup landing
├── /launch/[slug]                     Launch countdown pages (product releases)
│
├── /about                             Story, mission, team
├── /support                           Support hub: search, KB, contact
│   ├── /support/kb                    Knowledge base
│   │   └── /support/kb/[article]
│   └── /support/tickets → app         (redirects into dashboard if signed in)
├── /contact
├── /legal/terms · /legal/privacy · /legal/refunds · /legal/risk-disclaimer
│
├── /auth
│   ├── /auth/sign-in · /auth/sign-up · /auth/reset
│   └── /auth/callback                 OAuth / magic-link return
│
├── /app                               ── CUSTOMER DASHBOARD (auth required) ──
│   ├── /app                           Overview: products, signals, announcements
│   ├── /app/indicators                Purchased indicators + access status
│   │   └── /app/indicators/[slug]     Access mgmt, docs, updates for one product
│   ├── /app/licenses                  License portal: activate / transfer / deactivate
│   ├── /app/downloads                 Files, presets, templates
│   ├── /app/billing                   Plan, invoices, payment methods, cancel/upgrade
│   ├── /app/scanner                   Full market scanner (entitled users)
│   ├── /app/journal                   Trade journal (+ AI insights)
│   ├── /app/lex                       AI Copilot chat + chart upload
│   ├── /app/community                 Discord/Telegram linking, role sync status
│   ├── /app/referrals                 Affiliate dashboard: links, commissions, payouts
│   ├── /app/support                   Ticket list → /app/support/[ticket-id]
│   └── /app/settings                  Profile, TradingView username, notifications, security
│
└── /admin                             ── ADMIN PANEL (staff RBAC) ──
    ├── /admin                         KPI overview: MRR, churn, sales, tickets
    ├── /admin/products                CRUD indicators, bundles, media, docs
    │   └── /admin/products/[id]/versions   Upload updates, publish changelogs
    ├── /admin/pricing                 Plans, coupons, student discounts
    ├── /admin/customers               Search, view, impersonate (audited)
    │   └── /admin/customers/[id]      Entitlements, refunds, TV access, notes
    ├── /admin/licenses                Grants, revocations, TradingView sync queue
    ├── /admin/orders                  Orders, refunds, disputes
    ├── /admin/content                 Blog/guides/KB editor, publishing workflow
    ├── /admin/newsletters             Compose, segment, send (Resend broadcasts)
    ├── /admin/affiliates              Approvals, commission review, payouts
    ├── /admin/support                 Ticket queue, canned replies, SLAs
    ├── /admin/community               Moderation: ideas, requests, leaderboard flags
    ├── /admin/analytics               Funnels, cohorts, LTV, attribution
    └── /admin/settings                Team, roles, API keys, webhooks, feature flags
```

## Route-zone rules

| Zone | Layout | Auth | Rendering |
|------|--------|------|-----------|
| Public | `(marketing)` layout — transparent nav → solid on scroll, footer | None | Static/ISR, edge-cached |
| App | `(app)` layout — sidebar nav, no marketing chrome | Session required | Dynamic, streamed RSC |
| Admin | `(admin)` layout — dense data UI | Session + `staff` role + 2FA | Dynamic, no cache |

## Redirect & vanity map

- `/discord`, `/telegram`, `/youtube`, `/x`, `/tiktok`, `/instagram` → tracked 302s (UTM-stamped)
- `/buy/[slug]` → checkout deep-link for ads and video descriptions
- `/r/[code]` → affiliate short link (sets 60-day attribution cookie → product page)

## Sitemap.xml strategy

Generated at build + revalidated on content publish. Split sitemaps:
`/sitemap-products.xml`, `/sitemap-learn.xml`, `/sitemap-blog.xml`, `/sitemap-glossary.xml`
under a sitemap index — keeps Google crawling content types at different cadences.
`/app` and `/admin` are `noindex` and excluded entirely.
