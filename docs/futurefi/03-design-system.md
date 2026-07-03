# 03 — Design System "FF Obsidian"

Premium, dark-first, restrained. The rule that keeps it Apple-level: **one accent doing
one job**. Gold is *only* for money/CTAs/success-of-purchase moments. Blue is *only* for
data/informational states. Everything else is a disciplined gray ramp on near-black.

## 1. Color tokens

```css
:root {
  /* ── Surfaces (near-black, slightly warm to flatter gold) ── */
  --ff-bg:          #0A0A0B;   /* page background */
  --ff-surface-1:   #111113;   /* cards, panels */
  --ff-surface-2:   #18181B;   /* elevated: modals, popovers */
  --ff-surface-3:   #1F1F23;   /* highest: dropdowns, tooltips */
  --ff-border:      #26262B;   /* hairline borders */
  --ff-border-hover:#3A3A41;

  /* ── Text ── */
  --ff-text:        #F5F5F7;   /* primary — not pure white (halation) */
  --ff-text-2:      #A1A1AA;   /* secondary */
  --ff-text-3:      #63636B;   /* muted, captions */
  --ff-text-inverse:#0A0A0B;   /* on gold */

  /* ── Gold — the money accent (CTAs, prices, premium badges) ── */
  --ff-gold:        #E8B84B;   /* primary accent */
  --ff-gold-bright: #F6D06B;   /* hover, gradient stop */
  --ff-gold-dim:    #8A6D2F;   /* pressed, borders */
  --ff-gold-glow:   rgba(232, 184, 75, 0.16);  /* glows, focus rings */
  --ff-gradient-gold: linear-gradient(135deg, #F6D06B 0%, #E8B84B 45%, #C89430 100%);

  /* ── Blue — the data accent (links, info, chart UI, selected states) ── */
  --ff-blue:        #4C7DFF;
  --ff-blue-dim:    #2C4A99;
  --ff-blue-glow:   rgba(76, 125, 255, 0.14);

  /* ── Semantic / market colors ── */
  --ff-bull:        #22C57A;   /* up / success */
  --ff-bear:        #F4506A;   /* down / error  */
  --ff-warn:        #F5A623;
  --ff-bull-bg:     rgba(34, 197, 122, 0.10);
  --ff-bear-bg:     rgba(244, 80, 106, 0.10);
}
```

**Light mode** exists only for docs/blog reading (`prefers-color-scheme` + toggle on
content pages): `--ff-bg:#FAFAF8`, surfaces white, gold darkens to `#B98A24` for AA
contrast. Marketing + app remain dark-only — it's the brand.

### Contrast guarantees (WCAG AA)
- `--ff-text` on `--ff-bg`: 17.4:1 ✓ · `--ff-text-2` on surfaces: ≥ 6:1 ✓
- Gold is used as *background* with `--ff-text-inverse` (8.9:1 ✓), never as body-text color
  on dark at small sizes; gold text is allowed ≥ 18px semibold (prices, stats).

## 2. Typography

| Role | Font | Notes |
|------|------|-------|
| Display / headings | **Suisse Intl** (or free: **Inter Display**) | Tracking −2% above 32px |
| Body / UI | **Inter** (variable) | 16px base, 1.6 line-height |
| Numbers / data / code | **JetBrains Mono** | Tabular figures for prices & stats |

Scale (1.250 major third, `clamp()` for fluid headings):

```
display-xl  clamp(44px, 6vw, 72px) / 1.05 / 700     hero only
display     clamp(36px, 4.5vw, 56px) / 1.1 / 700
h1 40 · h2 32 · h3 24 · h4 20   (weight 600)
body-lg 18 · body 16 · body-sm 14 · caption 12 (uppercase, +6% tracking)
data-lg 28 mono · data 16 mono
```

Rules: max 2 weights per view. Headline style is sentence case (not ALL CAPS) except
`caption` eyebrow labels. Numbers in tables/stats always mono + tabular.

## 3. Spacing, layout, radius

- **4px base grid.** Scale: 4 8 12 16 24 32 48 64 96 128.
- Container: `max-width: 1200px` (marketing), `1440px` fluid (app/admin). Gutter 24/16px.
- Breakpoints: `sm 640 · md 768 · lg 1024 · xl 1280`.
- Radius: `--r-sm 6px` (inputs, chips) · `--r-md 10px` (buttons) · `--r-lg 16px` (cards)
  · `--r-xl 24px` (hero media, modals). Never fully-round rectangles; pills only for chips.
- Section rhythm on marketing pages: 96px desktop / 64px mobile between sections.

## 4. Elevation & depth

Dark UIs get depth from **borders + subtle light**, not drop shadows:

```css
.card        { background: var(--ff-surface-1); border: 1px solid var(--ff-border); }
.card:hover  { border-color: var(--ff-border-hover); transform: translateY(-2px); }
.card-premium{ border: 1px solid var(--ff-gold-dim);
               box-shadow: 0 0 40px -12px var(--ff-gold-glow); }   /* featured only */
.modal       { background: var(--ff-surface-2);
               box-shadow: 0 24px 64px -16px rgba(0,0,0,.6); }
```

One signature flourish, used sparingly (hero, pricing highlight): a 1px gold gradient
border via `border-image` / masked pseudo-element, and a faint radial gold glow behind
hero media. If everything glows, nothing is premium.

## 5. Motion (Framer Motion)

| Token | Value | Use |
|-------|-------|-----|
| `ease-out-expo` | `cubic-bezier(0.16, 1, 0.3, 1)` | Everything entering |
| `duration-fast` | 150ms | Hovers, toggles |
| `duration-base` | 250ms | Cards, dropdowns |
| `duration-slow` | 500ms | Section reveals, hero |

Patterns:
- **Section reveal**: `opacity 0→1, y 24→0`, stagger children 60ms, trigger at 20% in-view, once.
- **Counter stats**: spring count-up when scrolled into view.
- **Chart hero**: candles draw left→right on load (KCharts render loop), signals pop in with a 1.06 scale spring.
- **Buttons**: 150ms background/`translateY(-1px)`; press `scale(0.98)`.
- Respect `prefers-reduced-motion`: swap all movement for opacity fades.
- Budget: no more than one continuously-animating element per viewport (the chart owns it).

## 6. Iconography & imagery

- Icons: **Lucide**, 1.5px stroke, 20px UI / 24px feature. Gold fill only for premium/locked badges.
- Product imagery: real chart screenshots on `--ff-bg`-matched TradingView dark theme so
  they blend seamlessly into cards. Annotations in gold/blue only.
- No stock photos of bulls, rockets, or men pointing at screens — ever. Charts are the imagery.

## 7. Voice & microcopy

- Confident, precise, zero hype: "Verified backtests" not "INSANE WIN RATE 🚀".
- Numbers over adjectives. Every performance claim links to methodology.
- Disclaimers are styled as first-class UI (`.disclaimer` block: `--ff-warn` left border,
  `--ff-text-2`), never 8px gray footnotes — regulators and smart customers both notice.

## 8. Tailwind wiring

Tokens live in `globals.css` as CSS variables (above) and are mapped in Tailwind v4
`@theme` so classes read semantically: `bg-surface-1 text-primary border-hairline
text-gold data-mono`. Never hard-code hex in components — the token layer is the design
system's API.
