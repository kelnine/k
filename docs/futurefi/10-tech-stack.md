# 10 — Tech Stack

Chosen for: solo-founder velocity now, no rewrite at 100k users later, and edges
competitors can't copy (the in-house chart engine).

## The stack

| Layer | Choice | Why (vs. alternatives) |
|-------|--------|------------------------|
| Framework | **Next.js 15+ (App Router) + React + TypeScript** | RSC = fast marketing pages and dynamic app in one codebase; ISR for product/content pages; the hiring pool. |
| Styling | **Tailwind CSS v4** + CSS variables token layer | Design system as tokens (doc 03); v4 is fast and CSS-first. |
| Components | **shadcn/ui** (Radix) + Framer Motion | Owned code, full restyle freedom, a11y built in. Motion only where doc 03 allows. |
| Charts | **KCharts — this repo's engine** (`src/engine/`) | The moat. Playground, product previews, results curves all run in-house — no TradingView widget limits (widgets can't show custom Pine), no licensing risk. Extract to `packages/kcharts`. |
| Database + Auth + Storage + Realtime | **Supabase (Postgres)** | One vendor for the data spine; RLS matches our security model (doc 05); Realtime powers live license-sync status and scanner; escape hatch = it's just Postgres. |
| Auth choice | **Supabase Auth** (not Clerk) | Free at scale, same vendor as data, RLS-native `auth.uid()`. Clerk is lovely but $0.02+/MAU forever and a second user store to sync. Google OAuth + email/password + magic links. |
| Payments | **Stripe** (+ Stripe Tax, Checkout, Customer Portal-parity UI) · **PayPal SDK** · **Coinbase Commerce** | Doc 09. Merchant of record stays us for margin. |
| Jobs/queues | **Vercel Cron** (MVP) → **Inngest** (Phase 2) | TV sync queue, drips, reconciliation. Inngest gives retries/steps/observability without infra. |
| Email | **Resend** + React Email templates | Transactional + Broadcasts (newsletter) in one; templates in the repo, versioned like code. |
| Content | **MDX in-repo** (MVP) → **Sanity** (Phase 2, when non-dev editors exist) | Don't buy a CMS before you have an editor who isn't you. |
| AI (Lex) | **Claude API** via Vercel AI SDK; `/api/ai/*` namespace | Vision (chart-image analysis) + structured outputs; indicator knowledge base as RAG over our own docs. Isolated service boundary from day one. |
| Hosting | **Vercel** behind **Cloudflare** (DNS, WAF, bot rules, rate limits on auth/webhooks) | Preview deploys, edge network, zero-ops. |
| Analytics | **PostHog** (product + funnels + flags + session replay) + **Vercel Analytics** (web vitals) + **GSC** | One tool for funnels AND feature flags AND replays beats three tools. |
| Errors/monitoring | **Sentry** + Vercel logs + **Checkly** uptime (checkout + webhook probes) | The webhook probe is the one that saves revenue. |
| Repo layout | Turborepo: `apps/web`, `apps/admin`(or route-group), `packages/kcharts`, `packages/ui`, `packages/db` (types + zod), `packages/emails` | The existing KCharts code slots straight into `packages/kcharts`. |

## Performance budget (enforced in CI via Lighthouse)

- Marketing pages: LCP < 1.8 s, CLS < 0.05, JS < 170 KB gz first load.
- Techniques: RSC-first, `next/image` + AVIF, chart previews as `<video>` WebM (not GIF
  — 10× smaller), video facades, ISR with on-publish revalidation, fonts self-hosted
  variable subsets, KCharts lazy-loaded below fold with `IntersectionObserver`.

## Security checklist

- RLS on every table (doc 05); service-role key only in server/webhook contexts.
- Webhook signature verification + idempotency ledger.
- Admin: role check in middleware **and** per-action; 2FA required; audit log.
- Rate limits (Cloudflare + Upstash): auth 5/min, checkout 10/min, Lex 20/day/user tiered.
- CSP headers, no third-party scripts except payments + PostHog.
- Secrets in Vercel env; quarterly rotation; least-privilege API keys.

## SEO plumbing (tech side; strategy in doc 11)

Next Metadata API per route · JSON-LD components (Product, Review, Article, FAQPage,
BreadcrumbList, Organization) · split sitemaps + index · canonical URLs · OG images
generated per product/post via `@vercel/og` · `robots.txt` blocking `/app` `/admin`.

## What we deliberately do NOT use

- **No TradingView embed widgets for product demos** — they can't render our Pine
  scripts; KCharts replicas of the indicator logic (already largely written in
  `src/indicators/smc.ts`) demo it better and load faster.
- **No microservices** — a modular monolith with clean boundaries (`billing`,
  `entitlements`, `tv-sync`, `ai`, `content`) until real scale demands otherwise.
- **No Kubernetes/self-hosting** — Vercel+Supabase until >$1M ARR makes egress math interesting.
- **No Redux** — RSC + TanStack Query + Zustand slivers where needed.
