# 06 — User Flow Diagrams

The flows that make or lose money, in order of importance.

## 1. Visitor → Customer (the core funnel)

```mermaid
flowchart TD
    A[Traffic: SEO / YouTube / X / Ads / Affiliate link] --> B{Lands on}
    B -->|/blog, /learn| C[Content page<br/>inline product CTA]
    B -->|/indicators/slug| D[Product page]
    B -->|/| E[Home]
    B -->|/r/code| RC[Set 60-day affiliate cookie] --> D
    E --> D
    C --> D
    D --> F{Convinced?}
    F -->|Not yet| G[Try in Playground]
    G --> G2{Engaged 60s+ / 2 indicators}
    G2 -->|Email gate| H[Lead captured<br/>source=playground]
    H --> I[5-part email drip:<br/>setup → results → strategy → social proof → offer]
    I --> D
    F -->|Not yet, price| J[/free indicator/] --> H
    F -->|Yes| K[Plan picker: Monthly / Annual / Lifetime]
    K --> L{Payment method}
    L -->|Card / Apple / Google Pay| M[Stripe Checkout]
    L -->|PayPal| N[PayPal flow]
    L -->|Crypto| O[Coinbase Commerce charge]
    M --> P[webhook: payment succeeded]
    N --> P
    O --> P
    P --> Q[Create account if new<br/>+ entitlements + TV grant job]
    Q --> R[Success page:<br/>1. Set TradingView username<br/>2. 'Access granted in ~5 min'<br/>3. Join Discord]
    R --> S[Onboarding checklist in /app]
```

**Conversion levers marked in the wireframes:** playground gate, sticky mobile buy bar,
annual-plan anchoring, bundle upsell on every product page, exit-intent free-indicator
offer (max once per session).

## 2. First-run activation (post-purchase — where churn is decided)

```mermaid
flowchart TD
    A[Payment success page] --> B{TV username on file?}
    B -->|No| C[Inline TvUsernameField<br/>validated format]
    C --> D[Grant job queued]
    B -->|Yes| D
    D --> E[Job worker grants invite-only access]
    E -->|ok| F[Email + in-app: 'You're live —<br/>add it to your chart' + 2-min video]
    E -->|fail ×5| G[Alert admin queue +<br/>apology email w/ ETA]
    F --> H{Added to chart within 48h?}
    H -->|No| I[Nudge email: setup walkthrough<br/>+ offer of setup call/Discord help]
    H -->|Yes| J[Day-3 email: entry examples<br/>Day-7: strategy guide<br/>Day-14: review ask]
```

## 3. Free-indicator lead magnet

```mermaid
flowchart LR
    A[/free/slug] --> B[Email form<br/>source tagged]
    B --> C[Instant: TV access link +<br/>welcome email]
    C --> D[Drip: value ×3 →<br/>discount offer day 7]
    D --> E{Buys?}
    E -->|Yes| F[Lead.converted_user_id set<br/>attribution recorded]
    E -->|No| G[Monthly newsletter pool]
```

## 4. Cancel / retention flow

```mermaid
flowchart TD
    A[/app/billing → Cancel/] --> B[Reason survey<br/>1 required click]
    B -->|Too expensive| C[Offer: 40% off next 3 months<br/>or downgrade to single indicator]
    B -->|Not using it| D[Offer: pause up to 3 months<br/>keeps access frozen, no charge]
    B -->|Missing feature| E[Link feature request + offer month free when shipped]
    B -->|Other/firm| F[Confirm cancel]
    C & D & E -->|Declined| F
    F --> G[cancel_at_period_end=true<br/>access until period end]
    G --> H[Winback email day 30:<br/>what shipped since you left]
```

## 5. Support flow (deflection-first)

```mermaid
flowchart TD
    A[User has problem] --> B[/support search/]
    B -->|KB answers| C[Solved — no ticket]
    B -->|No| D{Signed in?}
    D -->|Yes| E[New ticket: category + product<br/>auto-attaches plan & TV sync state]
    D -->|No| F[Email form → ticket]
    E --> G{Category}
    G -->|access| H[Auto-diagnostic: entitlement ✓? TV job state?<br/>If failed job → auto-retry + reply template]
    G -->|billing/refund| I[Staff queue, SLA 24h]
    G -->|bug| J[Editor/dev queue]
    H & I & J --> K[Resolution → satisfaction rating]
```

## 6. Community engagement loop (retention engine)

```mermaid
flowchart LR
    A[Customer] --> B[Discord/Telegram<br/>role-synced by entitlement]
    A --> C[Posts trade idea<br/>w/ FF chart screenshot]
    C --> D[Votes → monthly leaderboard]
    D --> E[Top 3 win: free month /<br/>lifetime upgrade credit]
    A --> F[Feature request + votes]
    F --> G[Roadmap: Planned → Building → Shipped]
    G --> H[Shipped email to voters<br/>'you asked, we built']
    E & H --> A
```

## 7. Affiliate flow

```mermaid
flowchart TD
    A[User applies /affiliates] --> B{Auto-checks:<br/>account 30d+, purchase?}
    B -->|Pass| C[Approved → code + dashboard]
    B -->|Manual| D[Admin review]
    C --> E[Shares /r/code]
    E --> F[Click logged, 60-day cookie]
    F --> G[Order paid → commission pending 30%]
    G --> H[30-day refund window passes → approved]
    H --> I[Balance ≥ $50 → monthly payout<br/>PayPal / crypto / Stripe]
    G -->|Refund| J[Commission reversed]
```

## 8. Lex (AI Copilot) session — Phase 3

```mermaid
flowchart TD
    A[/app/lex/] --> B{Entitled to AI tier?}
    B -->|No| C[Preview mode: 3 free analyses/mo<br/>→ upsell]
    B -->|Yes| D[Upload chart image or pick symbol]
    D --> E[Vision model + FF indicator knowledge base<br/>structured output: bias, levels, setup, invalidation, R:R]
    E --> F[Response card + disclaimer footer]
    F --> G[One-click: save to journal /<br/>share to community ideas]
    G --> H[Journal entries feed AI weekly review:<br/>'your best setup is OB-retest on 4H']
```
