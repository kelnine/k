# 02 — Wireframes

Annotated wireframes for every page template. Mobile-first: each layout collapses to a
single column; the notes call out mobile behavior where it differs. `▸` marks a
conversion-critical element.

Conventions: `[Button]` primary gold CTA · `(Button)` secondary ghost · `{…}` dynamic data.

---

## 1. Home `/`

```
┌──────────────────────────────────────────────────────────────┐
│ ◆ FutureFi   Indicators  Playground  Results  Learn  Pricing │  Sticky nav, blur bg
│                                    (Sign in)  [Get Started]  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│        TRADE WITH AN EDGE,                                   │  H1, 64px, white
│        NOT A GUESS.                                          │  "EDGE" in gold
│   Institutional-grade TradingView indicators, verified       │  Sub, 20px, gray
│   results, and an AI copilot built by traders.               │
│                                                              │
│   ▸[Explore Indicators]   (Try the Playground →)             │
│                                                              │
│   ┌────────────────────────────────────────────────────┐    │
│   │  LIVE ANIMATED CHART — KCharts engine rendering    │    │  Real engine, real
│   │  BTC with Smart Money Pro overlay: order blocks,   │    │  signals, subtle
│   │  BOS labels, entry arrow animating in on scroll    │    │  parallax. Canvas,
│   └────────────────────────────────────────────────────┘    │  not video = fast
│                                                              │
│   Trusted by {4,200+} traders · ★★★★★ {4.9} · 🛡 30-day guarantee │  Social proof strip
├──────────────────────────────────────────────────────────────┤
│  FLAGSHIP INDICATORS                        (View all →)     │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │  Product cards w/
│  │ chart   │ │ chart   │ │ chart   │ │ chart   │            │  looping preview on
│  │ preview │ │ preview │ │ preview │ │ preview │            │  hover (mobile: 
│  │ Sniper  │ │ Smart   │ │ Breakout│ │ Scalper │            │  autoplay in view)
│  │ Pro     │ │ Money   │ │ AI      │ │         │            │
│  │ ${79}/mo│ │ ${99}/mo│ │ ${89}/mo│ │ ${59}/mo│            │
│  │ [View]  │ │ [View]  │ │ [View]  │ │ [View]  │            │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘            │
├──────────────────────────────────────────────────────────────┤
│  SEE IT IN ACTION                                            │
│  ┌──────────────────────────────┐  ● 90-sec product film    │  Video: poster +
│  │      ▶ video (16:9)          │  ● Chapter list at right  │  lazy YouTube embed
│  └──────────────────────────────┘                            │
├──────────────────────────────────────────────────────────────┤
│  VERIFIED PERFORMANCE                                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                │  Animated counters
│  │ {68%}  │ │ {2.4}  │ │ {1.9k} │ │ {12}   │                │  count up on scroll
│  │ win rt │ │ profit │ │ trades │ │ markets│                │
│  └────────┘ └────────┘ └────────┘ └────────┘                │
│  Backtested {2019–2026}, methodology published → /results    │  ▸ Honesty = trust
│  ⚠ Past performance is not indicative of future results.    │  Disclaimer visible,
├──────────────────────────────────────────────────────────────┤  not buried
│  WHAT TRADERS SAY                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │  Carousel; avatars,
│  │ ★★★★★    │ │ ★★★★★    │ │ ★★★★★    │                     │  name, market they
│  │ "quote"  │ │ "quote"  │ │ "quote"  │                     │  trade. Video
│  └──────────┘ └──────────┘ └──────────┘                     │  testimonials later
├──────────────────────────────────────────────────────────────┤
│  FAQ (accordion ×6: refunds, TradingView setup, lifetime…)   │  FAQPage schema.org
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────┐     │
│  │  Get a free indicator + weekly market breakdowns   │     │  ▸ Email capture
│  │  [ email………………… ] [Send it]                        │     │  band, gold border
│  └────────────────────────────────────────────────────┘     │
├──────────────────────────────────────────────────────────────┤
│ FOOTER: Products | Learn | Company | Legal | Socials         │
│ Risk disclaimer paragraph. © FutureFi. Not financial advice. │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Indicator catalog `/indicators`

```
┌──────────────────────────────────────────────────────────────┐
│  Indicators                                                  │
│  Filters:  [Style ▾ Scalp/Swing/SMC]  [Market ▾]  [Price ▾]  │  Filter chips; URL-
│  Sort: Popular ▾                          {8} products       │  synced for SEO/share
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐      │
│  │ animated prev │ │               │ │               │      │  3-col → 1-col.
│  │ Sniper Pro    │ │ PA Suite      │ │ Smart Money   │      │  Card: preview, name,
│  │ Precision     │ │ Price-action  │ │ ICT/SMC       │      │  one-liner, badges
│  │ entries       │ │ toolkit       │ │ toolkit       │      │  (NEW/BESTSELLER),
│  │ ★4.9 · 1.2k   │ │ ★4.8 · 800    │ │ ★4.9 · 2.1k   │      │  rating, from-price
│  │ from ${59}/mo │ │ from ${49}/mo │ │ from ${79}/mo │      │
│  └───────────────┘ └───────────────┘ └───────────────┘      │
│  ┌──────────────────────────────────────────────┐           │
│  │ BUNDLE BANNER: Complete Suite — save {35%}   │           │  ▸ Bundle upsell row
│  └──────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Product page `/indicators/[slug]` — the money template

```
┌──────────────────────────────────────────────────────────────┐
│ breadcrumb: Indicators / Smart Money Pro                     │
│ ┌───────────────────────────────┐  FutureFi SMART MONEY PRO  │  Above fold: name,
│ │  HERO MEDIA: autoplaying      │  ★4.9 ({2,113} reviews)    │  rating, pitch, price
│ │  chart loop of the indicator  │  Order blocks, BOS/CHoCH,  │  & CTA visible with
│ │  (WebM, <2 MB) with tabs:     │  liquidity — automated.    │  ZERO scrolling
│ │  ▶Video · GIFs · Screens      │                            │
│ │                               │  ${99}/mo · ${790}/yr      │
│ └───────────────────────────────┘  ${1,490} lifetime         │
│                                    ▸[Get Smart Money Pro]    │  Opens plan modal
│                                    (Try in Playground)       │  ▸ Risk-free trial
│                                    ✓ 30-day guarantee        │
│                                    ✓ Instant TradingView access │
├──────────────────────────────────────────────────────────────┤
│ STICKY SUBNAV: Overview·Features·Examples·Results·Docs·      │  Sticks under main
│               Changelog·Roadmap·Pricing·FAQ                  │  nav; scroll-spy
├──────────────────────────────────────────────────────────────┤
│ OVERVIEW   2-col: narrative + annotated hero screenshot      │
│ FEATURES   6–9 feature cards, each w/ zoomed GIF crop        │
│ SUPPORTED  Markets: Forex·Crypto·Gold·Indices·Stocks         │  Icon grid +
│            Timeframes: 1m–1W (badge per TF)                  │  compat table
│ ENTRY EXAMPLES  Before/after slider on real charts,          │  ▸ Teaches the trade,
│                 3 annotated setups (long, short, reversal)   │  sells the tool
│ EXIT EXAMPLES   Same pattern: TP laddering, SL logic         │
│ RESULTS    Equity curve + stats table + link to /results     │
│            ⚠ disclaimer inline                               │
│ DOCS       First 2 sections inline, "Read full docs →"       │
│ CHANGELOG  v3.2 {date} — timeline, latest 3, expandable      │  Proof of active dev
│ VERSIONS   Table: version · date · highlights                │
│ ROADMAP    Now / Next / Later columns (from feature votes)   │
│ PRICING    3 plan cards (Monthly/Annual★/Lifetime) + bundle  │  ★ = "Most popular"
│            upsell: "Also in Complete Suite — save 35%"       │
│ REVIEWS    Verified-purchase reviews, filter by rating       │
│ FAQ        Product-specific accordion                        │
│ CROSS-SELL "Pairs well with" — 3 cards                       │
├──────────────────────────────────────────────────────────────┤
│ MOBILE: sticky bottom bar [ ${99}/mo ▾ | Get Access ]        │  ▸ Always-visible buy
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Playground `/playground`

```
┌──────────────────────────────────────────────────────────────┐
│  Try FutureFi indicators on a live chart — free, no signup   │
│ ┌────────┬──────────────────────────────────────────────┐   │
│ │Symbol  │                                              │   │  KCharts engine.
│ │search  │        FULL LIVE CHART (KCharts)             │   │  Real Binance data.
│ │TF: 15m │        + selected indicator overlay          │   │  Indicator params
│ │────────│                                              │   │  locked to defaults
│ │☑ Smart │                                              │   │  (full control is a
│ │  Money │                                              │   │  paid feature ▸)
│ │☐ Sniper│                                              │   │
│ │☐ Break │  ┌─────────────────────────────────┐         │   │
│ │  out AI│  │ Like what you see? [Get access] │         │   │  Soft CTA after 60s
│ └────────┴──┴─────────────────────────────────┴─────────┘   │  or 3 indicator swaps
│  After 2 indicators: email gate — "unlock all previews"  ▸  │  Lead capture
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Pricing `/pricing`

```
┌──────────────────────────────────────────────────────────────┐
│        Simple pricing. Serious tools.                        │
│        [ Monthly | Annual –20% | Lifetime ]   ← segmented    │
│  ┌────────────┐ ┌═════════════┐ ┌────────────┐              │
│  │ SINGLE     │ ║ COMPLETE ★  ║ │ LIFETIME   │              │  Middle card gold
│  │ INDICATOR  │ ║ SUITE       ║ │ EVERYTHING │              │  border, elevated,
│  │ from $49/mo│ ║ $149/mo     ║ │ $2,990 once│              │  "Most popular"
│  │ pick one   │ ║ all 7 + Lex ║ │ + all future│             │
│  │ [Choose]   │ ║ ▸[Start]    ║ │ [Own it]   │              │
│  └────────────┘ ╚═════════════╝ └────────────┘              │
│  ✓ 30-day money-back  ✓ Cancel anytime  ✓ Student –30% →    │
│  Feature comparison table (sticky first column on mobile)    │
│  Payment logos: Visa·MC·Amex·PayPal··Pay·GPay·BTC·ETH·USDC  │
│  FAQ: billing, upgrades, lifetime terms, coupons             │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. Results `/results`

```
│  VERIFIED PERFORMANCE                                        │
│  Methodology banner: how we backtest, data source, costs     │  ▸ Radical honesty
│  Per indicator: equity curve · win rate · PF · max DD ·      │  = the moat. Every
│  trade count · per-market breakdown · settings used          │  number reproducible
│  [Download full backtest CSV]                                │
│  Live-tracking section (optional): broker-verified feed      │
│  ⚠ Standalone risk-disclaimer block, always visible          │
```

## 7. Free indicators `/free`

```
│  Grid of 3–4 free tools. Card → modal:                       │
│  "Enter email to get instant access" → success screen with   │  ▸ Email magnet.
│  TradingView link + onboarding email drip (5-part)           │  Tag source per tool
```

## 8. Learning Center `/learn` & Blog `/blog`

```
│  /learn hub: 4 tiles (Guides·Tutorials·Strategies·Glossary)  │
│  + featured course + search                                  │
│  Article template: TOC left rail (sticky), 720px prose col,  │  Reading progress
│  author card, related posts, inline indicator CTAs,          │  bar. Article schema.
│  "used in this guide" product footer                         │  ▸ Every article
│  Blog index: featured post + category chips + grid           │  sells something
```

## 9. AI hub `/ai` & Lex `/app/lex`

```
│  /ai — vision page: Lex hero (chat mockup animating),        │  Marketing surface
│  suite cards (Scanner·Journal·Risk·Analysis), waitlist ▸     │  for Phase 3; ships
│                                                              │  as waitlist in MVP
│  /app/lex — chat UI: left history rail, main thread,         │
│  [Upload chart 📷] → Lex annotates: bias, entry idea,        │
│  invalidation, R:R — grounded in FutureFi indicator logic    │
│  ⚠ every response footer: "analysis, not financial advice"   │
```

## 10. Community `/community`

```
│  Hub: Discord/Telegram join cards (member counts),           │
│  Leaderboard preview (top 10, monthly), Trade ideas feed     │
│  (cards: chart screenshot·author·votes), Feature requests    │
│  (list + upvote ▲, status chips: Planned/Building/Shipped)   │
```

## 11. Customer dashboard `/app`

```
┌────────┬─────────────────────────────────────────────────────┐
│ ◆ FF   │  Welcome back, {name}                               │
│        │  ┌ Plan: Complete Suite (Annual) · renews {date} ┐  │  Status strip
│ Home   │  └ TradingView: ✓ linked as {tv_user} ┘            │
│ Indic. │  MY INDICATORS                                      │
│ Licen. │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │  Card: status dot
│ Downl. │  │ Smart    │ │ Sniper   │ │ Breakout │            │  (● active), version,
│ Scanner│  │ Money ✓  │ │ Pro ✓    │ │ AI  ⟳    │            │  [Open in TV] [Docs]
│ Journal│  └──────────┘ └──────────┘ └──────────┘            │  ⟳ = update available
│ Lex    │  WHAT'S NEW   {changelog feed}                      │
│ Refer. │  QUICK ACTIONS: Join Discord · Get support · Refer  │
│ Billing│                                                     │
│ Support│                                                     │
│ Settin.│                                                     │
└────────┴─────────────────────────────────────────────────────┘
Mobile: sidebar → bottom tab bar (Home·Indicators·Lex·More)
```

## 12. License portal `/app/licenses`

```
│  TRADINGVIEW ACCESS                                          │
│  TV username: [ {tv_user} ] (Change)  → re-sync warning      │  ▸ Self-serve. Change
│  Per product row:                                            │  = auto revoke old +
│  Smart Money Pro   ● Active   granted {date}                 │  grant new, rate-
│                    (Deactivate) (Transfer…)                  │  limited 1/30 days
│  Sync status timeline: Requested → Granted (audit trail)     │
```

## 13. Billing `/app/billing`

```
│  Current plan card: name, price, renewal, [Upgrade] (Cancel) │  Cancel = retention
│  Payment methods (Stripe elements) · Invoice history table   │  flow: offer pause /
│  Crypto payments: status + tx links                          │  downgrade first
```

## 14. Support `/app/support` + tickets

```
│  Search KB first (deflection) → "Still stuck? Open ticket"   │
│  New ticket: category ▾ · product ▾ · description · attach   │
│  Thread view: messages, status chip, satisfaction rating     │
```

## 15. Affiliate dashboard `/app/referrals`

```
│  Your link: futurefi.io/r/{code}  [Copy]                     │
│  Stats: Clicks · Signups · Conversions · Earnings · Pending  │
│  Payout: method (PayPal/crypto/Stripe) · threshold $50       │
│  Assets: banners, tweet templates, video snippets            │
```

## 16. Admin panel `/admin` (dense-data layout)

```
┌────────┬─────────────────────────────────────────────────────┐
│ Overvw │  MRR {${42.3k}} ↑8% · Active subs {1,204} · Churn   │  KPI header row
│ Product│  {2.1%} · Open tickets {7} · Failed payments {3}    │
│ Pricing│  Revenue chart (30/90/365d) · Recent orders table   │
│ Custom.│  Alerts: TV sync failures, disputes, refund queue   │
│ License│                                                     │
│ Orders │  Each section = table + detail drawer pattern:      │
│ Content│  filter bar → data table → row click → right drawer │
│ News.  │  with tabs (details / activity / danger zone)       │
│ Affil. │                                                     │
│ Support│  Product editor: form + live preview of the public  │
│ Analyt.│  product page side-by-side                          │
│ Setting│                                                     │
└────────┴─────────────────────────────────────────────────────┘
```

## 17. Launch page `/launch/[slug]`

```
│  {Product name} — dropping {date}                            │
│  Countdown ⏱ DD:HH:MM:SS · teaser video · feature teasers    │
│  ▸ [Join waitlist — early-bird 25% off] (email capture)      │
│  Post-launch: page 301s to the product page                  │
```

## 18. Auth screens

```
│  Split screen: left = form (email+password, Google, magic    │
│  link), right = animated chart + testimonial. Sign-up asks   │
│  ONLY email+password; TradingView username is asked later,   │  ▸ Don't add friction
│  at first product activation (contextual, higher completion) │  before payment
```
