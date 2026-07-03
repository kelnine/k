# 05 — Database Schema (Postgres / Supabase)

Design principles:

1. **Stripe is the billing source of truth; the DB mirrors it.** We never compute
   billing state locally — webhooks project Stripe state into `subscriptions`/`orders`,
   and **`entitlements` is the single table the app reads to answer "what can this user
   access?"** Products, bundles, lifetime, subs, manual grants — all collapse into it.
2. **Everything auditable.** Money, licenses, and admin actions get append-only logs.
3. **RLS everywhere.** Users read their own rows; staff roles gate the rest; billing
   tables are written only by the service role (webhooks/jobs).

```sql
-- ═══════════════════════════ EXTENSIONS / ENUMS ═══════════════════════════
create extension if not exists "pgcrypto";

create type user_role         as enum ('customer','support','editor','admin','owner');
create type product_kind      as enum ('indicator','bundle','course','ai_tool');
create type product_status    as enum ('draft','coming_soon','published','archived');
create type price_interval    as enum ('month','year','lifetime');
create type order_status      as enum ('pending','paid','failed','refunded','partially_refunded','disputed');
create type payment_provider  as enum ('stripe','paypal','coinbase_commerce');
create type sub_status        as enum ('trialing','active','past_due','canceled','paused','incomplete');
create type entitlement_status as enum ('active','pending','suspended','expired','revoked');
create type entitlement_source as enum ('subscription','lifetime','free','trial','manual','affiliate_reward');
create type tv_sync_status    as enum ('queued','processing','granted','revoked','failed');
create type ticket_status     as enum ('open','pending_customer','pending_staff','resolved','closed');
create type affiliate_status  as enum ('pending','approved','suspended');
create type commission_status as enum ('pending','approved','paid','reversed');
create type request_status    as enum ('under_review','planned','building','shipped','declined');

-- ═══════════════════════════ IDENTITY ═══════════════════════════
-- auth.users is managed by Supabase Auth; profiles extends it 1:1.
create table profiles (
  id                uuid primary key references auth.users on delete cascade,
  email             text not null,
  display_name      text,
  avatar_url        text,
  role              user_role not null default 'customer',
  tradingview_username text,                -- the linchpin for access delivery
  tv_username_changed_at timestamptz,       -- enforce change cooldown (30 d)
  discord_id        text,
  telegram_id       text,
  country           text,                   -- tax + student-discount checks
  marketing_opt_in  boolean not null default false,
  stripe_customer_id text unique,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- ═══════════════════════════ CATALOG ═══════════════════════════
create table products (
  id              uuid primary key default gen_random_uuid(),
  slug            text unique not null,        -- 'smart-money-pro'
  kind            product_kind not null default 'indicator',
  status          product_status not null default 'draft',
  name            text not null,
  tagline         text,
  description     text,                        -- MDX
  hero_media_url  text,
  gallery         jsonb not null default '[]', -- [{type:'video'|'gif'|'image', url, caption}]
  features        jsonb not null default '[]',
  markets         text[] not null default '{}',    -- {'forex','crypto','gold',...}
  timeframes      text[] not null default '{}',    -- {'1m','5m','15m','1H','4H','1D'}
  tv_script_id    text,                        -- TradingView pub script id (invite-only)
  docs_slug       text,
  seo             jsonb not null default '{}', -- {title, description, ogImage}
  sort_order      int not null default 0,
  published_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table bundle_items (               -- bundles are products (kind='bundle')
  bundle_id  uuid references products on delete cascade,
  product_id uuid references products on delete cascade,
  primary key (bundle_id, product_id)
);

create table prices (                     -- mirrors Stripe Prices
  id               uuid primary key default gen_random_uuid(),
  product_id       uuid not null references products on delete cascade,
  interval         price_interval not null,
  amount_cents     int not null,
  currency         text not null default 'usd',
  stripe_price_id  text unique,
  active           boolean not null default true,
  created_at       timestamptz not null default now(),
  unique (product_id, interval, currency, active) deferrable  -- one live price per interval
);

create table product_versions (
  id           uuid primary key default gen_random_uuid(),
  product_id   uuid not null references products on delete cascade,
  version      text not null,             -- '3.2.0'
  title        text,
  changelog    text not null,             -- MDX
  file_url     text,                      -- optional download (presets, templates)
  published_at timestamptz,
  created_at   timestamptz not null default now(),
  unique (product_id, version)
);

create table roadmap_items (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid references products on delete cascade,  -- null = company-wide
  title       text not null,
  description text,
  bucket      text not null check (bucket in ('now','next','later')),
  status      request_status not null default 'planned',
  sort_order  int not null default 0
);

-- ═══════════════════════════ COMMERCE ═══════════════════════════
create table coupons (                    -- mirror of Stripe coupons + our metadata
  id               uuid primary key default gen_random_uuid(),
  code             text unique not null,
  stripe_coupon_id text,
  percent_off      int,
  amount_off_cents int,
  kind             text not null default 'general',  -- general|student|launch|winback
  max_redemptions  int,
  redeemed_count   int not null default 0,
  expires_at       timestamptz,
  active           boolean not null default true
);

create table orders (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references profiles,
  status            order_status not null default 'pending',
  provider          payment_provider not null,
  provider_ref      text,                 -- payment_intent / paypal order / charge code
  subtotal_cents    int not null,
  discount_cents    int not null default 0,
  tax_cents         int not null default 0,
  total_cents       int not null,
  currency          text not null default 'usd',
  coupon_id         uuid references coupons,
  affiliate_id      uuid,                  -- fk added after affiliates table
  crypto_currency   text,                  -- 'BTC'|'ETH'|'SOL'|'USDC'
  crypto_tx_hash    text,
  refunded_cents    int not null default 0,
  created_at        timestamptz not null default now(),
  paid_at           timestamptz
);

create table order_items (
  id           uuid primary key default gen_random_uuid(),
  order_id     uuid not null references orders on delete cascade,
  product_id   uuid not null references products,
  price_id     uuid references prices,
  interval     price_interval not null,
  amount_cents int not null
);

create table subscriptions (              -- projection of Stripe subscriptions
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references profiles,
  stripe_subscription_id text unique,
  status                 sub_status not null,
  price_id               uuid references prices,
  product_id             uuid not null references products,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  canceled_at            timestamptz,
  pause_until            timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

-- ═══════════ ENTITLEMENTS — the heart of the system ═══════════
-- One row = "user X can use product Y (until Z)". Everything reads THIS,
-- never orders/subscriptions directly. Bundles fan out to per-product rows.
create table entitlements (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles,
  product_id      uuid not null references products,
  status          entitlement_status not null default 'pending',
  source          entitlement_source not null,
  source_id       uuid,                    -- order_id | subscription_id | null(manual)
  expires_at      timestamptz,             -- null = lifetime/free
  granted_by      uuid references profiles, -- staff id for manual grants
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (user_id, product_id, source, source_id)
);
create index on entitlements (user_id) where status = 'active';

create table tv_access_jobs (             -- TradingView grant/revoke sync queue
  id           uuid primary key default gen_random_uuid(),
  entitlement_id uuid not null references entitlements on delete cascade,
  action       text not null check (action in ('grant','revoke')),
  tv_username  text not null,
  tv_script_id text not null,
  status       tv_sync_status not null default 'queued',
  attempts     int not null default 0,
  last_error   text,
  processed_at timestamptz,
  created_at   timestamptz not null default now()
);
create index on tv_access_jobs (status, created_at) where status in ('queued','failed');

create table license_events (             -- append-only audit for the license portal
  id             uuid primary key default gen_random_uuid(),
  entitlement_id uuid not null references entitlements,
  actor_id       uuid references profiles,     -- user or staff
  event          text not null,   -- activated|deactivated|transferred|tv_username_changed|granted|revoked|expired
  detail         jsonb not null default '{}',
  created_at     timestamptz not null default now()
);

-- ═══════════════════════════ LEADS & CONTENT ═══════════════════════════
create table leads (
  id          uuid primary key default gen_random_uuid(),
  email       text not null,
  source      text not null,      -- 'free:{slug}'|'playground'|'newsletter'|'launch:{slug}'
  utm         jsonb not null default '{}',
  converted_user_id uuid references profiles,
  created_at  timestamptz not null default now(),
  unique (email, source)
);

create table posts (                       -- blog, guides, tutorials, KB (one engine)
  id           uuid primary key default gen_random_uuid(),
  slug         text unique not null,
  channel      text not null check (channel in ('blog','guide','tutorial','strategy','kb','glossary')),
  title        text not null,
  excerpt      text,
  body         text,                       -- MDX
  cover_url    text,
  author_id    uuid references profiles,
  category     text,
  tags         text[] not null default '{}',
  related_product_ids uuid[] not null default '{}',
  seo          jsonb not null default '{}',
  status       text not null default 'draft' check (status in ('draft','review','published')),
  published_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table reviews (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles,
  product_id  uuid not null references products,
  rating      int not null check (rating between 1 and 5),
  body        text,
  verified    boolean not null default false,  -- set true if buyer (trigger checks entitlement)
  status      text not null default 'pending' check (status in ('pending','published','rejected')),
  created_at  timestamptz not null default now(),
  unique (user_id, product_id)
);

-- ═══════════════════════════ COMMUNITY ═══════════════════════════
create table trade_ideas (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles,
  title       text not null,
  body        text,
  chart_url   text,
  symbol      text,
  direction   text check (direction in ('long','short')),
  product_ids uuid[] not null default '{}',
  status      text not null default 'published' check (status in ('published','flagged','removed')),
  created_at  timestamptz not null default now()
);

create table feature_requests (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles,
  product_id  uuid references products,
  title       text not null,
  body        text,
  status      request_status not null default 'under_review',
  created_at  timestamptz not null default now()
);

create table votes (
  user_id     uuid references profiles on delete cascade,
  subject_type text not null check (subject_type in ('trade_idea','feature_request')),
  subject_id  uuid not null,
  value       int not null default 1 check (value in (1)),
  created_at  timestamptz not null default now(),
  primary key (user_id, subject_type, subject_id)
);

-- ═══════════════════════════ SUPPORT ═══════════════════════════
create table tickets (
  id          uuid primary key default gen_random_uuid(),
  number      bigint generated always as identity,   -- human-friendly #1042
  user_id     uuid not null references profiles,
  product_id  uuid references products,
  category    text not null,      -- billing|access|bug|question|refund
  subject     text not null,
  status      ticket_status not null default 'open',
  assignee_id uuid references profiles,
  satisfaction int check (satisfaction between 1 and 5),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table ticket_messages (
  id         uuid primary key default gen_random_uuid(),
  ticket_id  uuid not null references tickets on delete cascade,
  author_id  uuid not null references profiles,
  body       text not null,
  attachments jsonb not null default '[]',
  is_internal boolean not null default false,   -- staff-only notes
  created_at timestamptz not null default now()
);

-- ═══════════════════════════ AFFILIATES ═══════════════════════════
create table affiliates (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid unique not null references profiles,
  code           text unique not null,          -- /r/{code}
  status         affiliate_status not null default 'pending',
  commission_pct int not null default 30,
  payout_method  jsonb not null default '{}',   -- {type:'paypal'|'crypto'|'stripe', ...}
  created_at     timestamptz not null default now()
);
alter table orders add constraint orders_affiliate_fk
  foreign key (affiliate_id) references affiliates;

create table referral_clicks (
  id           uuid primary key default gen_random_uuid(),
  affiliate_id uuid not null references affiliates,
  landing_path text,
  utm          jsonb not null default '{}',
  created_at   timestamptz not null default now()
);

create table commissions (
  id           uuid primary key default gen_random_uuid(),
  affiliate_id uuid not null references affiliates,
  order_id     uuid not null references orders,
  amount_cents int not null,
  status       commission_status not null default 'pending',  -- approve after refund window
  approved_at  timestamptz,
  paid_at      timestamptz,
  payout_ref   text,
  created_at   timestamptz not null default now(),
  unique (order_id)          -- one commission per order
);

-- ═══════════════════════════ AI (Phase 3) ═══════════════════════════
create table journal_entries (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references profiles,
  symbol     text not null,
  direction  text check (direction in ('long','short')),
  entry_price numeric, exit_price numeric, size numeric,
  risk_r     numeric,                       -- planned R
  result_r   numeric,                       -- realized R
  setup_tags text[] not null default '{}',  -- {'ob-retest','fvg','breakout'}
  product_ids uuid[] not null default '{}',
  chart_url  text,
  notes      text,
  ai_review  jsonb,                         -- Lex's structured critique
  opened_at  timestamptz, closed_at timestamptz,
  created_at timestamptz not null default now()
);

create table lex_conversations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references profiles,
  title      text,
  created_at timestamptz not null default now()
);
create table lex_messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references lex_conversations on delete cascade,
  role            text not null check (role in ('user','assistant')),
  content         text not null,
  image_url       text,
  tokens_used     int,
  created_at      timestamptz not null default now()
);

create table scanner_signals (             -- written by the signal worker (bot/)
  id         uuid primary key default gen_random_uuid(),
  product_id uuid not null references products,
  symbol     text not null,
  timeframe  text not null,
  signal     text not null,                -- 'bos_long'|'ob_retest_short'|...
  detail     jsonb not null default '{}',
  fired_at   timestamptz not null default now()
);
create index on scanner_signals (fired_at desc);

-- ═══════════════════════════ OPS ═══════════════════════════
create table audit_log (                   -- every admin mutation
  id         uuid primary key default gen_random_uuid(),
  actor_id   uuid references profiles,
  action     text not null,                -- 'refund.issue','entitlement.revoke','impersonate.start'
  subject_type text, subject_id text,
  detail     jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table webhook_events (              -- idempotency ledger for Stripe/PayPal/Coinbase
  id           text primary key,           -- provider event id
  provider     payment_provider not null,
  type         text not null,
  payload      jsonb not null,
  processed_at timestamptz,
  error        text,
  created_at   timestamptz not null default now()
);

create table feature_flags (
  key        text primary key,
  enabled    boolean not null default false,
  rules      jsonb not null default '{}'    -- {roles:[], percent:10, userIds:[]}
);
```

## Row-Level Security (summary)

```sql
-- Pattern per table (examples; apply across the board):
alter table entitlements enable row level security;
create policy "own entitlements" on entitlements for select
  using (auth.uid() = user_id);
-- writes to entitlements/orders/subscriptions/commissions: service_role only (no policy)

create policy "staff read all" on entitlements for select
  using (exists (select 1 from profiles p
                 where p.id = auth.uid() and p.role in ('support','admin','owner')));

-- products/prices/posts: public SELECT where status='published'; editor+ for writes
-- tickets/ticket_messages: owner or staff; is_internal rows hidden from customers
-- trade_ideas/feature_requests/votes: public read, authenticated insert own, staff moderate
-- audit_log/webhook_events: service_role + owner read only
```

## Key derived views

```sql
-- The single question the app asks constantly:
create view active_entitlements as
  select user_id, product_id, max(coalesce(expires_at,'infinity')) as access_until
  from entitlements
  where status = 'active' and (expires_at is null or expires_at > now())
  group by user_id, product_id;

create view mrr as                          -- admin KPI
  select date_trunc('month', now()) as month,
         sum(p.amount_cents / case pr.interval when 'year' then 12 else 1 end) as mrr_cents
  from subscriptions s
  join prices p on p.id = s.price_id
  join prices pr on pr.id = s.price_id
  where s.status in ('active','trialing');
```

## Lifecycle triggers (implemented as Postgres functions or Inngest jobs)

- `order paid` → create entitlements (bundle → fan out) → enqueue `tv_access_jobs(grant)` → create commission (pending) → receipt email.
- `subscription canceled/past_due (final)` → expire entitlements → enqueue `revoke` → winback email.
- `tv_username changed` → re-enqueue revoke(old)+grant(new) for all active entitlements; enforce 30-day cooldown.
- `refund issued` → mark order, reverse commission, optionally revoke entitlements.
- Nightly: expire stale entitlements, retry failed TV jobs (max 5, exponential), approve commissions older than the 30-day refund window.
