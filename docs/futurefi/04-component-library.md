# 04 — Component Library

Base layer: **shadcn/ui** (Radix primitives, owned code, restyled with FF Obsidian
tokens) — accessibility (focus traps, ARIA, keyboard nav) comes free and we keep full
visual control. On top of it, the FutureFi domain layer below. Naming: `ff-*` prefix in
`src/components/{ui,marketing,product,app,admin}/`.

## Foundations (restyled shadcn)

`Button` `Input` `Select` `Checkbox` `Switch` `Tabs` `Accordion` `Dialog` `Drawer`
`Popover` `Tooltip` `Toast` `Badge` `Avatar` `Skeleton` `Table` `DropdownMenu`
`Command(⌘K)` `Progress` `Slider`

Button variants:

| Variant | Look | Use |
|---|---|---|
| `primary` | Gold gradient bg, dark text | THE buy/CTA button — one per viewport |
| `secondary` | `surface-2` bg, hairline border | Everything else |
| `ghost` | Transparent, text-2 → text | Nav, tertiary |
| `outline-gold` | Gold border, transparent | Secondary CTAs near a primary |
| `danger` | `bear` colors | Destructive, admin |

Sizes `sm 32 / md 40 / lg 48`; all support `loading` (spinner swaps label, width locked).

## Marketing components

| Component | Props (key) | Notes |
|-----------|-------------|-------|
| `NavBar` | `variant: transparent\|solid` | Blur-glass on scroll; mobile sheet menu; session-aware (CTA ↔ avatar) |
| `Hero` | `headline, sub, ctas[], media` | Media slot takes `LiveChart` |
| `LiveChart` | `symbol, indicators[], animate` | KCharts engine wrapper; lazy, `IntersectionObserver`-gated |
| `ProductCard` | `product, badge?, showPrice` | Hover: preview video plays, gold border fades in |
| `BundleBanner` | `bundle, savingsPct` | Full-width upsell row |
| `PriceCard` | `plan, featured?, interval` | Featured = gold border + glow |
| `IntervalToggle` | `intervals[], onChange` | Monthly/Annual/Lifetime segmented control |
| `StatCounter` | `value, label, suffix, decimals` | Spring count-up in view |
| `EquityCurve` | `series, drawdownShade` | Results charts (blue line, bear-red DD shade) |
| `TestimonialCarousel` | `items[]` | Drag + auto-advance, pause on hover |
| `VideoPlayer` | `poster, src, chapters?` | Facade pattern: poster → click → load embed (perf) |
| `BeforeAfterSlider` | `before, after` | Entry/exit example charts |
| `FaqAccordion` | `items[]` | Emits FAQPage JSON-LD |
| `EmailCaptureBand` | `source, incentive` | Tagged lead magnet; inline success state |
| `CountdownTimer` | `target, onExpire` | Launch pages |
| `LogoTicker` | `logos[]` | Markets/press strip, slow marquee |
| `ComparisonTable` | `plans[], features[]` | Sticky first column on mobile |
| `RiskDisclaimer` | `variant: inline\|block` | Standardized legal block |
| `SectionHeading` | `eyebrow, title, sub` | Enforces rhythm/consistency |

## Product-page components

`MediaGallery` (video/GIF/screenshot tabs, swipe on mobile) · `FeatureGrid` ·
`MarketBadges` + `TimeframeBadges` · `SetupExample` (annotated chart + entry/SL/TP
legend) · `ChangelogTimeline` · `VersionTable` · `RoadmapColumns` (Now/Next/Later) ·
`ReviewList` + `ReviewStars` (aggregate emits Product JSON-LD) · `StickyBuyBar`
(mobile bottom bar: price select + CTA) · `PlanPickerModal` (interval → plan →
checkout handoff) · `DocsLayout` (sidebar tree, prose column, breadcrumbs, version
switcher) · `TocRail` (scroll-spy).

## App (dashboard) components

`AppShell` (sidebar ↔ mobile bottom tabs) · `PlanStatusStrip` · `EntitlementCard`
(status dot: active/pending-sync/update-available/expired; actions: Open in TV, Docs,
Manage) · `TvUsernameField` (validate + re-sync warning + cooldown note) ·
`LicenseRow` (activate/deactivate/transfer + confirm dialogs) · `SyncTimeline`
(audit trail: requested→granted→revoked) · `InvoiceTable` · `PaymentMethodList`
(Stripe Elements) · `CancelFlow` (multi-step retention: reason → pause/downgrade offer
→ confirm) · `TicketList` / `TicketThread` / `NewTicketForm` · `ReferralStats` ·
`ReferralLinkCard` (copy + QR) · `JournalEntryForm` / `JournalTable` / `JournalStats` ·
`LexChat` (thread, streaming responses, chart-image upload, disclaimer footer) ·
`ScannerTable` (live signals: symbol, TF, signal, age; blurred rows + upsell when
unentitled) · `NotificationBell` · `OnboardingChecklist` (link TV → add to chart →
join Discord → first docs read).

## Admin components

`KpiCard` (value, delta arrow, spark) · `RevenueChart` · `DataTable` (TanStack:
server pagination, filters, column pins, CSV export) · `DetailDrawer` (row click →
right panel, tabs: Details/Activity/Danger) · `ProductForm` (+ live preview pane) ·
`VersionUploader` (file + notes → publish pipeline) · `CouponForm` · `CustomerHeader`
(LTV, plan, risk flags) · `EntitlementEditor` (grant/revoke + reason, audited) ·
`RefundDialog` (full/partial, auto-revoke toggle) · `SyncQueueTable` (TV job states,
retry button) · `RichEditor` (TipTap: MDX blocks, image upload) · `NewsletterComposer`
(segment builder → preview → test-send → schedule) · `AffiliatePayoutTable` ·
`ImpersonateButton` (banner while active, fully audited) · `AuditLogViewer` ·
`FeatureFlagTable`.

## Shared utility components

`Money` (currency + interval formatting, mono) · `RelativeTime` · `MarkdownProse`
(docs/blog typography) · `EmptyState` (illustration + CTA) · `ErrorBoundary` ·
`SeoJsonLd` (Product/Article/FAQ/Breadcrumb schema) · `TrackedLink` (analytics +
affiliate params) · `GatedContent` (blur + lock + upsell for unentitled features).

## Conventions

- Server Components by default; `"use client"` only for interactivity (charts, forms, motion).
- Every component states: variants, sizes, `loading`/`disabled`/`error`, empty state, dark-only or dual-theme.
- Storybook from Phase 2 onward; until then a `/dev/kitchen-sink` route renders everything for visual QA.
- No component imports raw hex/px — tokens only (see 03).
