# FutureFi — Platform Design Package

> The complete blueprint for building FutureFi from a premium indicator storefront into a
> full-scale fintech software company. Written to be executed: every document is a build
> spec, not a mood board.

## What FutureFi is

FutureFi sells professional TradingView Pine Script indicators, strategies, AI trading
tools, and education — with the ambition to compete with LuxAlgo, TrendSpider, and
TradingView itself on polish, trust, and product depth.

**Positioning statement:** *"Institutional-grade trading tools, engineered — not hyped."*

The brand wins on three axes competitors are weak on:

1. **Verifiable trust** — public backtests with honest disclaimers, versioned changelogs,
   real documentation. Most indicator sellers hide methodology; FutureFi publishes it.
2. **Self-serve everything** — license activation/transfer/deactivation, downloads,
   refunds status, all without a support ticket. LuxAlgo still gates this behind Discord DMs.
3. **A real product roadmap** — AI Copilot (Lex), market scanner, strategy builder,
   marketplace. Indicators are the wedge; the platform is the business.

**Unfair advantage already in this repo:** the KCharts engine (`src/engine/`) — a custom
canvas charting engine with SMC overlays and a live signals bot. FutureFi's interactive
"try before you buy" playground runs on our own engine with our own indicator logic,
something no TradingView-widget-embedding competitor can do (TradingView widgets cannot
render third-party Pine scripts).

## Document index

| # | Document | Contents |
|---|----------|----------|
| 01 | [Sitemap](./01-sitemap.md) | Full URL tree, every route, public/auth/admin zones |
| 02 | [Wireframes](./02-wireframes.md) | Annotated wireframes for every page template |
| 03 | [Design System](./03-design-system.md) | Color, type, spacing, motion, dark-mode tokens |
| 04 | [Component Library](./04-component-library.md) | Every UI component with props and states |
| 05 | [Database Schema](./05-database-schema.md) | Complete Postgres/Supabase SQL, RLS policies |
| 06 | [User Flows](./06-user-flows.md) | Mermaid diagrams: visitor → buyer → power user |
| 07 | [Admin Workflow](./07-admin-workflow.md) | Admin panel spec and operational runbooks |
| 08 | [Customer Workflow](./08-customer-workflow.md) | Dashboard, license portal, support lifecycle |
| 09 | [Subscription Architecture](./09-subscription-architecture.md) | Billing engine, Stripe/crypto, TradingView access sync |
| 10 | [Tech Stack](./10-tech-stack.md) | Recommended stack with reasoning and alternatives |
| 11 | [SEO Strategy](./11-seo-strategy.md) | Keyword map, content engine, technical SEO |
| 12 | [Marketing Pages](./12-marketing.md) | Affiliate, ambassador, social, launch machinery |
| 13 | [Roadmap](./13-roadmap.md) | Phased plan: MVP → growth → AI platform → enterprise |

## The one-paragraph architecture

Next.js 15 (App Router, TypeScript) on Vercel behind Cloudflare; Tailwind CSS 4 +
Framer Motion for the premium dark UI; Supabase (Postgres + Auth + Storage + Realtime)
as the data spine with Row-Level Security; Stripe as the billing source of truth
(subscriptions, lifetime, coupons, tax) with Coinbase Commerce for crypto; a small
worker layer (Vercel cron + QStash) that syncs paid entitlements to TradingView
invite-only script access; Resend for transactional email + newsletters; Sanity (or MDX
in-repo at MVP) for content; PostHog for product analytics. The AI layer (Lex) is a
separate service boundary from day one — an `/api/ai/*` namespace backed by the Claude
API — so it can scale independently.

## Reading order for builders

1. `10-tech-stack.md` → `05-database-schema.md` → `09-subscription-architecture.md` (the machine)
2. `03-design-system.md` → `04-component-library.md` → `02-wireframes.md` (the skin)
3. `13-roadmap.md` (what to build first — resist building everything at once)
