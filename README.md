# Mojo

A freelance work marketplace backend. Clients post jobs and fund them; workers bid using passes; payment is held in escrow until work is approved. Built with Django + DRF, deployed on Vercel, Postgres on Supabase, Paystack for payments, WhatsApp for OTP.


## Table of Contents

1. [Architecture](#architecture)
2. [Local Setup](#local-setup)
3. [Environment Variables](#environment-variables)
4. [Running the Server](#running-the-server)
5. [API Reference](#api-reference)
6. [Core Flows](#core-flows)
7. [Deployment](#deployment)
8. [Crons](#crons)
9. [Admin Panel](#admin-panel)
10. [Project Structure](#project-structure)

---

## Architecture

```
Client ──► Django API (Vercel) ──► Postgres (Supabase)
                  │
                  ├──► Paystack (deposits, pass purchases)
                  ├──► WhatsApp Bot (OTP delivery)
                  └──► M-Pesa B2C (worker withdrawals)
```

**Money model:** Every wallet is a row in `ledger_wallet`. Every balance change is an immutable `ledger_transaction` row. Escrow is tracked in `ledger_escrowhold`. Money never appears or disappears; it only moves between wallets.

**Four wallet types:**

| Wallet | Owner | Purpose |
|---|---|---|
| `client` | One per client | Client deposits and refunds |
| `worker_earnings` | One per worker | `pending` (48h hold) → `available` (withdrawable) |
| `worker_pass` | One per worker | Pass balance for bidding |
| `platform` | One singleton | Platform fee revenue |

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js (only for Vercel CLI, optional)
- Git

### Install

```bash
git clone <repo>
cd Mojo
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### `.env`

Copy `.env.example` to `.env` and fill in:

```env
DJANGO_SECRET_KEY=dev-key-change-me
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Leave blank locally — Django falls back to SQLite
DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=

# Paystack (test keys until production)
PAYSTACK_SECRET_KEY=
PAYSTACK_PUBLIC_KEY=
PAYSTACK_CALLBACK_URL=http://localhost:3000/wallet/callback
PASS_PRICE_KES=10

# WhatsApp bot
WHATSAPP_URL=
WHATSAPP_TOKEN=

# Cron (Vercel sets this automatically in production)
CRON_SECRET=

# Domain config (defaults in settings.py)
MOJO_PLATFORM_FEE_PCT=0.10
MOJO_PENDING_HOLD_HOURS=48
MOJO_AUTO_APPROVE_DAYS=5
MOJO_MAX_REVISIONS=2
```

### Migrate

```bash
python manage.py migrate
python manage.py seed_pass_tiers
python manage.py createsuperuser
```

### Migrate against Supabase (one-off, when deploying)

Get the **Transaction pooler** hostname from Supabase Dashboard → Connect → Transaction pooler, then:

```bash
export DB_HOST="aws-0-REGION.pooler.supabase.com"
export DB_PORT="6543"
export DB_NAME="postgres"
export DB_USER="postgres.<project-ref>"
export DB_PASSWORD="your-password"

python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('db ok')"
python manage.py migrate
python manage.py seed_pass_tiers

unset DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | ✅ | Long random string (≥64 chars for production) |
| `DJANGO_DEBUG` | ✅ | `1` locally, `0` on Vercel |
| `DJANGO_ALLOWED_HOSTS` | ✅ | Comma-separated. Include `.vercel.app` for Vercel |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Production | Blank locally → SQLite fallback |
| `PAYSTACK_SECRET_KEY` | For payments | `sk_test_...` or `sk_live_...` |
| `PAYSTACK_PUBLIC_KEY` | For payments | `pk_test_...` or `pk_live_...` |
| `PAYSTACK_CALLBACK_URL` | For payments | Where Paystack redirects after payment |
| `PASS_PRICE_KES` | Optional | Price per pass in KES (default 10) |
| `WHATSAPP_URL` | For OTP | Your bot's `/send-dm` endpoint |
| `WHATSAPP_TOKEN` | Optional | Bearer token for the bot |
| `CRON_SECRET` | Vercel-set | Vercel auto-injects this |

---

## Running the Server

```bash
python manage.py runserver
```

- API: `http://localhost:8000/api/`
- Admin: `http://localhost:8000/admin/`
- Health check: `http://localhost:8000/api/jobs/feed/` (401 without auth = running correctly)

---

## API Reference

### Auth

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register/` | Public | Register worker or client. Body: `{role, username, password, phone, email?, business_name?}` |
| POST | `/api/auth/login/` | Public | Body: `{username, password}` → `{user, tokens}` |
| POST | `/api/auth/refresh/` | Public | Body: `{refresh}` → `{access}` |
| GET | `/api/auth/me/` | JWT | Current user + profile |
| POST | `/api/auth/otp/issue/` | JWT | Request OTP to phone. Body: `{purpose: "signup"}` |
| POST | `/api/auth/otp/verify/` | JWT | Body: `{purpose, code}` → sets `is_verified=true` |
| POST | `/api/auth/otp/resend/` | JWT | Rate-limited resend |
| GET | `/api/auth/admin/otp/lookup/` | Admin | `?user_id=...&purpose=signup` — read active OTP code |

### Jobs

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/jobs/` | Client | Post job. Body: `{title, description, deadline, budget_min, budget_max, min_level, required_skill_ids, bid_window_hours}` |
| GET | `/api/jobs/feed/` | Worker | All biddable jobs with `locked`/`lock_reason`/`already_bid`/`can_bid` annotations |
| GET | `/api/jobs/my/` | Any | Role-dependent: posted jobs (client) or bid-on jobs (worker) |
| GET | `/api/jobs/{id}/` | JWT | Detail. Owner sees all bids; worker sees own bid |
| POST | `/api/jobs/{id}/bids/` | Worker | Place bid. Body: `{price, delivery_days, message}`. Charges passes |
| GET | `/api/jobs/{id}/top-bids/` | Client | Top 3 + recommended |
| POST | `/api/jobs/{id}/accept/{bid_id}/` | Client | Accept bid → escrow held → job `in_progress` |
| POST | `/api/jobs/{id}/deliver/` | Worker | Body: `{delivery_text?, delivery_file_url?}` |
| POST | `/api/jobs/{id}/approve/` | Client | Approve → escrow → 90% worker pending + 10% platform |
| POST | `/api/jobs/{id}/revise/` | Client | Request revision (max 2). Body: `{feedback}` |
| POST | `/api/jobs/{id}/cancel/` | Client | Cancel draft/open job. Refunds passes to bidders |
| POST | `/api/jobs/{id}/rate/` | JWT | Rate the other party after completion. Body: `{score: 1-5, comment?}` |
| GET | `/api/workers/{id}/reviews/` | Public | Worker's received ratings |

### Disputes

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/jobs/{id}/dispute/` | JWT | Open dispute. Body: `{reason, evidence_text?, evidence_file_url?}` |
| GET | `/api/disputes/{id}/` | JWT | Detail (parties + admin only) |
| POST | `/api/disputes/{id}/evidence/` | JWT | Body: `{text?, file_url?}` |
| POST | `/api/disputes/{id}/resolve/` | Admin | Body: `{outcome: "pay_worker"|"refund_client"|"split", note?, client_share?, worker_share?}` |

### Payouts

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/payouts/withdrawals/` | Worker | Request withdrawal. Body: `{amount, mpesa_number?}` |
| GET | `/api/payouts/withdrawals/list/` | Worker | Withdrawal history |
| POST | `/api/payouts/mpesa/callback/` | Public | M-Pesa B2C callback |
| POST | `/api/payouts/paystack/initiate/` | JWT | Body: `{purpose: "client_deposit"|"pass_purchase", amount_kes?, pass_count?}` → `{authorization_url, reference}` |
| POST | `/api/payouts/paystack/webhook/` | Public | Paystack `charge.success` webhook |

### Notifications

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/notifications/` | JWT | `?unread=1` for unread only |
| POST | `/api/notifications/{id}/read/` | JWT | Mark one read |
| POST | `/api/notifications/mark-all-read/` | JWT | Mark all read |

### Admin

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/admin/dashboard/` | Admin | Escrow, fees, active jobs, disputes, user counts |
| GET | `/api/admin/revenue/` | Admin | Fees by month, pass sales, lifetime fees |
| GET | `/api/admin/queue/disputes/` | Admin | Open/under-review disputes |
| GET | `/api/admin/settings/` | Admin | All runtime settings |
| GET | `/api/fraud/flags/` | Admin | Fraud flag log |
| GET | `/api/fraud/shared-ip/` | Admin | `?ip=...` — accounts sharing IP |
| GET | `/api/fraud/shared-device/` | Admin | `?ua_hash=...` — accounts sharing device |

### Cron (protected by `x-vercel-cron: 1` or `Bearer <CRON_SECRET>`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/internal/cron/auto-approve/` | Approve delivered jobs past 5-day window |
| GET | `/api/internal/cron/release-holds/` | Pending → available after 48h hold |
| GET | `/api/internal/cron/purge-otps/` | Delete OTPs older than 7 days |
| GET | `/api/internal/cron/recompute-levels/` | Recompute worker levels |

---

## Core Flows

### 1. Job posting → bidding → completion

```
Client deposits (Paystack)
   ↓
Client posts job (pass_cost computed from budget)
   ↓
Workers browse feed, place bids (each bid costs N passes)
   ↓
System scores all bids (price_fit + rating + completion + skill + past_client + new_worker_boost)
   ↓
Client sees top 3 + recommended, accepts one
   ↓
Escrow holds agreed price (client.available → escrow)
   ↓
Worker delivers → client approves
   ↓
Escrow releases (90% worker.pending, 10% platform.available)
   ↓
After 48h hold → worker.pending → worker.available
   ↓
Worker requests withdrawal → M-Pesa B2C
```

### 2. Pass purchase

```
Worker calls /api/payouts/paystack/initiate/ {purpose: "pass_purchase", pass_count: 20}
   ↓
Backend returns Paystack authorization_url
   ↓
Frontend redirects to Paystack checkout
   ↓
Worker pays via M-Pesa on phone
   ↓
Paystack fires charge.success webhook → backend credits 20 passes to worker_pass wallet
```

### 3. Dispute

```
Either party opens dispute while escrow is held
   ↓
Both submit evidence
   ↓
Admin resolves: pay_worker | refund_client | split
   ↓
Escrow released accordingly, job marked completed
```

### 4. Bid scoring

Each bid is scored out of 100 (weights configurable via `/admin/`):

| Component | Default weight |
|---|---|
| Price fit | 30 |
| Worker rating + accuracy | 30 |
| Completion rate | 20 |
| Skill match | 10 |
| Past client scores | 10 |
| **New worker boost** | up to +15 for first 5 jobs |

---

## Deployment

### Vercel

```bash
npm i -g vercel
vercel login
vercel link
vercel --prod
```

Vercel auto-detects Django via `manage.py`, runs `collectstatic`, and serves the WSGI app.

**Required Vercel env vars** (Production scope):

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (Supabase transaction pooler)
- `DJANGO_SECRET_KEY` (generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`)
- `DJANGO_DEBUG=0`
- `DJANGO_ALLOWED_HOSTS=your-app.vercel.app`
- `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_CALLBACK_URL`
- `WHATSAPP_URL`, `WHATSAPP_TOKEN`

`CRON_SECRET` is set automatically by Vercel.

### Post-deploy checks

```bash
curl https://your-app.vercel.app/api/jobs/feed/           # 401
curl https://your-app.vercel.app/api/internal/cron/release-holds/  # 403
```

Then update Paystack Dashboard → Webhook URL to `https://your-app.vercel.app/api/payouts/paystack/webhook/`.

---

## Crons

Defined in `vercel.json`. Requires **Vercel Pro** for hourly schedules:

```json
{
  "crons": [
    { "path": "/api/internal/cron/auto-approve/",     "schedule": "0 * * * *" },
    { "path": "/api/internal/cron/release-holds/",    "schedule": "0 * * * *" },
    { "path": "/api/internal/cron/purge-otps/",       "schedule": "0 4 * * *" },
    { "path": "/api/internal/cron/recompute-levels/", "schedule": "0 3 * * *" }
  ]
}
```

On Hobby, change hourly (`0 * * * *`) to daily (`0 0 * * *`).

---

## Admin Panel

Django admin: `/admin/`

Key admin views:
- **Wallets & Transactions** — read-only audit trail, every row immutable
- **Escrow Holds** — active and resolved
- **Jobs & Bids** — full state, inline bids, score breakdowns
- **Disputes** — evidence inline, resolution in Django admin or via API
- **OTP Codes** — read active plaintext codes (support flow when WhatsApp is down)
- **Settings** — edit `MOJO_*` values live; changes take effect on next API call
- **Fraud Flags, Device Fingerprints, Rate Limit Hits**

**Runtime-editable settings** (stored in `adminpanel.Setting`, cached 60s):

| Key | Default | Effect |
|---|---|---|
| `MOJO_PLATFORM_FEE_PCT` | `0.10` | % cut of every completed job |
| `MOJO_PENDING_HOLD_HOURS` | `48` | Hold before worker funds become withdrawable |
| `MOJO_AUTO_APPROVE_DAYS` | `5` | Auto-approve delivered jobs |
| `MOJO_MAX_REVISIONS` | `2` | Hard cap on revision requests |
| `MOJO_BID_WEIGHTS` | `30/30/20/10/10` | Scoring weights |
| `MOJO_NEW_WORKER` | `threshold: 5, max_boost: 15` | New-worker scoring boost |
| `MOJO_PASS_TIERS` | 4 tiers | Pass cost by bid budget |

---

## Project Structure

```
mojo/
├── manage.py
├── vercel.json
├── requirements.txt
├── .env.example
├── config/             # Django settings, URLs, WSGI
├── accounts/           # User, WorkerProfile, ClientProfile, OTPCode, auth
├── ledger/             # Wallet, Transaction, EscrowHold, ledger services
├── passes/             # PassTier, bid pass logic, daily grants
├── jobs/               # Job, Bid, scoring, state machine, HTTP views
├── payouts/            # Withdrawal, PendingPayment, Paystack, M-Pesa
├── disputes/           # Dispute, Evidence, resolution
├── reviews/            # Rating, worker/client stat recompute
├── fraud/              # Rate limits, device fingerprints, sanitization
├── notifications/      # In-app inbox, cron endpoints, WhatsApp adapter
└── adminpanel/         # Setting model, dashboard views, admin config
```

### Money invariants

1. **No balance is edited directly.** All changes go through `ledger/services.py`, wrapped in `@transaction.atomic` with `select_for_update`.
2. **Every transaction has a reference.** You can reconstruct any balance by summing its `ledger_transaction` rows.
3. **Escrow is created before work starts.** No escrow = no approval.
4. **Platform fees are a separate ledger row.** The platform wallet is a singleton; `get_platform_wallet()` returns the same row for every fee.

---

## Testing

```bash
# Apply migrations
python manage.py migrate
````
---

## License

Proprietary. All rights reserved.