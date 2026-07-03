# 12 — Marketing Pages & Growth Machinery

## Affiliate Program `/affiliates`

**Offer:** 30% recurring for 12 months on subscriptions, 30% one-time on lifetime.
60-day cookie. $50 payout threshold, monthly payouts (PayPal/crypto/Stripe).

Page: hero ("Earn 30% promoting tools you actually use") → earnings calculator slider
(referrals × plan → monthly income, animated) → how it works (3 steps) → asset preview
(banners, video clips, tweet templates) → commission table → FAQ (fraud rules, cookie,
payout schedule) → apply CTA. Application auto-approves existing customers in good
standing; manual review otherwise (doc 06 flow, dashboard in doc 02 §15).

## Ambassador Program `/ambassadors`

The tier above affiliates — for creators with an audience (5k+ followers or 1k+ YouTube
subs). Adds: 40% commission, free Complete Suite, early access to releases, co-branded
lead magnets, monthly strategy call, "FF Ambassador" Discord role + site profile.
Application form with social links; reviewed manually; quarterly performance review.
Page mirrors affiliate layout with a more exclusive tone ("Apply to join — 20 seats per
quarter").

## Social channel system

Vanity redirects (`/youtube` `/x` `/tiktok` `/instagram` `/discord` `/telegram`) are
UTM-stamped so PostHog attributes revenue per channel.

| Channel | Role | Content system |
|---------|------|----------------|
| **YouTube** | #1 converter in this niche | Weekly: strategy breakdowns using FF tools + market recaps. Every video: playground link + product link with UTM in the first two description lines. Each video gets an article twin (doc 11). |
| **X** | Authority + community | Daily chart posts from the bot (already in `bot/` — signal screenshots auto-tweeted), threads on setups, changelog announcements. |
| **TikTok/Instagram Reels** | Top-funnel volume | 30–60 s cuts of YouTube content: one setup, one payoff, playground CTA. Batch-produced. |
| **Discord/Telegram** | Retention + conversion | Free tier (previews, community) + customer tier (role-synced). Free members see signal teasers → conversion path. |
| **Newsletter** | Owned audience | Weekly "The Edge": one market insight, one setup teardown, one product/roadmap note. All leads (doc 05 `leads`) flow in with source tags. |

## Launch machinery `/launch/[slug]`

Repeatable product-launch playbook (page spec in doc 02 §17):

1. **T−14 d**: launch page live — countdown, teaser video, waitlist (early-bird 25%).
2. **T−7…−1**: teaser clips (TikTok/Reels/X), YouTube "something's coming" segment,
   two waitlist emails (feature reveal, results preview).
3. **T0**: waitlist email (24 h early-bird window) → public email → all-channel posts →
   Discord event. Page flips from countdown to buy module automatically.
4. **T+3 d**: "closing early-bird" email; **T+7**: results/testimonial recap.
5. Post-launch the page 301s to the product page (link equity).

Waitlist sizes are the launch KPI; every launch grows the list for the next one.

## Newsletter landing `/newsletter`

Single-purpose page: value promise, sample issue screenshot, subscriber count, one
field, one button. Lead magnet: free indicator + "SMC Cheat Sheet" PDF. Referral loop
later (share for bonus preset pack).

## Attribution stack

UTM discipline on every link → PostHog revenue attribution → weekly channel report in
`/admin/analytics` (CAC-ish per channel since spend is mostly time). Affiliate/ambassador
codes double as offline attribution ("use code LEX10" in videos).
