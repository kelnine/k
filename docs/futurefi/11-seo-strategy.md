# 11 — SEO Strategy

Trading-indicator SEO is a moderately competitive, high-intent niche where most
competitors have thin, hype-driven content. The strategy: **out-document everyone** —
Google and buyers both reward the site that actually explains how the thing works.

## Keyword map → URL map

| Cluster | Primary keywords | Target page | Intent |
|---------|-----------------|-------------|--------|
| Category head | best tradingview indicators (2026) | `/blog/best-tradingview-indicators` (annual flagship listicle, our products ranked honestly among free ones) | Commercial |
| Pine Script | pine script indicators, custom pine script | `/learn/guides/pine-script-indicators-guide` + `/indicators` | Mixed |
| ICT / SMC | ict indicators, smart money concepts indicator, order block indicator, fvg indicator | `/indicators/smart-money-pro` + supporting cluster: `/learn/strategies/ict-*`, `/learn/glossary/{order-block,fair-value-gap,bos,choch,liquidity-sweep}` | High commercial |
| Scalping | best scalping indicator, 1 minute scalping strategy | `/indicators/scalper` + `/learn/strategies/scalping-*` | High |
| Swing | swing trading indicators, best indicators for swing trading | `/indicators/swing-pro` + guides | High |
| Gold | gold trading indicator, xauusd strategy/indicator | `/blog/gold-trading-indicators` + market page `/markets/gold` | High |
| Crypto | crypto trading indicator, best indicators for crypto | `/markets/crypto` + guides | High |
| Forex | forex indicator, best forex indicators | `/markets/forex` + guides | High |
| Comparison | luxalgo alternative, luxalgo vs X, [competitor] review | `/blog/luxalgo-alternatives` etc. — honest comparisons convert stunningly well | Very high |
| Long-tail net | every SMC/ICT/TA term | `/learn/glossary/[term]` — 150+ short definitive pages, each linking to the relevant product | Top-funnel |

**Hub-and-spoke:** each product page is a hub; 5–10 supporting guides/glossary pages
per product link up to it with keyword-rich but natural anchors. Market pages
(`/markets/gold` etc.) aggregate "indicators + guides + results for {market}" — they
catch "{market} indicator" queries product pages can't.

## Content engine (cadence)

- **2 posts/week**: 1 strategy/education (evergreen, keyword-targeted) + 1 market
  analysis (freshness signal, social fodder).
- **Every YouTube video → article twin** (embed video, full transcript rewritten as
  prose). Double-dips the effort; video schema + watch-time both help.
- Quarterly: refresh the flagship listicles ("… in 2026") — date-in-title pages decay
  without it.
- Every post: author byline with credentials page (E-E-A-T), related products footer,
  internal links checked by a lint script (no orphans).

## Technical SEO (beyond doc 10 plumbing)

- Product pages emit `Product` + `AggregateRating` schema from real verified reviews →
  star snippets in SERPs (massive CTR edge in this niche; almost no competitor has them).
- FAQ schema on product + pricing pages; `Article`+`VideoObject` on tutorials;
  `BreadcrumbList` everywhere.
- Core Web Vitals as a ranking moat: competitors run bloated Wix/Webflow+widget sites;
  our budget (doc 10) makes speed a visible differentiator.
- Programmatic OG images per page (`@vercel/og`) for social CTR.

## Authority building (links)

1. **Free indicators published on TradingView** with House-of-tradingview profile links
   → the single best backlink + distribution channel in this niche. Each free script
   description links its `/free/[slug]` page.
2. Data-driven linkable assets: "We backtested {strategy} across 10,000 trades" studies
   — trading blogs and YouTubers cite these.
3. Guest analysis on trading publications; podcast circuit (trading podcasts are
   link-generous).
4. Affiliate/ambassador content naturally builds branded search + reviews.

## Honest-marketing constraint (also an SEO tactic)

No "95% win rate" claims — YMYL pages with unverifiable financial promises get
suppressed. Publishing methodology, drawdowns, and losing trades is simultaneously the
compliance posture, the trust brand, and the E-E-A-T signal.

## KPIs

Non-brand clicks/mo · top-3 rankings in each cluster · product-page organic CVR ·
glossary → product assisted conversions (PostHog) · referring domains. Review targets
quarterly; expect meaningful traction month 4–6, compounding after.
