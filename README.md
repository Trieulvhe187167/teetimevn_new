# TeeTimeVN

TeeTimeVN is a multi-lingual golf-course discovery and booking platform built with Flask. It combines a public course catalog, customer self-service flows, VNPay deposit payments, and rich admin/owner dashboards tailored to Vietnam-based partners.

## Feature Highlights
- Language-aware routing ( `/[zh-CN|zh-TW|en|vi|ja|ko]/...` ) driven by Flask-Babel, complete with per-locale SEO records and sitemap/robots helpers.
- Course discovery, ratings, and review management with localized content, filters, and top-course widgets rendered from SQLite.
- Customer booking workflow with tee-time availability APIs, optional service add-ons, deposit balances, cancellation/reschedule windows, and automated status history.
- Payment stack that supports VNPay redirects/IPN confirmations plus offline bank-transfer instructions and pay-at-course balances.
- Admin console for courses, pricing, FX, FAQ, evaluations, SEO strings, reviews, bookings, and user management.
- Owner portal for partner courses to review dashboards, bookings, and check-ins without needing admin access.
- Authentication with registration, login, and password reset emails powered by Flask-Mail.

## Repository Layout
| Path | Description |
| --- | --- |
| `app.py` | Application factory, language switcher, Flask-Mail/Babel config, and SEO helpers (sitemap, robots). |
| `modules/` | Blueprint implementations (`courses`, `booking`, `payments`, `payment_vnpay`, `admin`, `auth`, `owner`, `owner_support`, `review`, `faq`, `fx`, `news`, `total_merit`, etc.). |
| `templates/` | Public, auth, booking, admin, owner, FAQ, and email Jinja templates (for example `templates/index.html`, `templates/booking.html`, `templates/admin/*`, `templates/owner/*`). |
| `static/` | Front-end assets such as `static/css/main.css`, images, and `static/robots.txt`. |
| `data/` | SQLite database (`data/teetimevn_dev.db`) plus migration/seed/update utilities (`create_*`, `upgrade_*`, `seed_*`, `update_*`, map scripts, SEO loaders). |
| `docs/booking_flexibility.md` | Rollout guidance covering cancellation/reschedule rules, VNPay deposits, and QA tips. |
| `translations/`, `messages.pot`, `babel.cfg`, `i18n.sh` | Babel catalogs for every locale alongside extraction/compile helpers. |
| `tools/fill_missing_po.py` | Utility that removes `fuzzy` flags and mirrors `msgid` strings into empty `msgstr` entries. |
| `requirements.txt` | Python dependency lockfile (Flask, Flask-Babel, Flask-Mail, sqlite helpers, Pandas/Numpy, MySQL connectors, etc.). |

## Getting Started
### 1. Prerequisites
- Python 3.10+ (project tested on 3.11)
- SQLite 3 (bundled with Python)
- VNPay sandbox credentials (for payment testing)
- SMTP provider credentials (Gmail App Password or similar)

### 2. Create and activate a virtual environment
```powershell
cd C:\Users\dmx\Downloads\teetimevn
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables
`app.py` ships with dev-friendly defaults, but production secrets must live in the environment. Example PowerShell snippet:

```powershell
set SECRET_KEY=change-me
set FLASK_ENV=development

set MAIL_SERVER=smtp.gmail.com
set MAIL_PORT=587
set MAIL_USE_TLS=1
set MAIL_USERNAME=your-email@example.com
set MAIL_PASSWORD=app-password
set MAIL_DEFAULT_SENDER="Teetime VN <your-email@example.com>"

set BOOKING_CANCEL_WINDOW_HOURS=24
set BOOKING_RESCHEDULE_WINDOW_HOURS=12
set BOOKING_SLOT_CAPACITY=4
set BOOKING_DEPOSIT_PERCENT=20
set BOOKING_ALERT_EMAIL=ops@example.com

set VNPAY_TMN_CODE=xxx
set VNPAY_HASH_SECRET=super-secret
set VNPAY_PAYMENT_URL=https://sandbox.vnpayment.vn/paymentv2/vpcpay.html
set VNPAY_RETURN_URL=https://your-host/payment/vnpay/return
set VNPAY_IPN_URL=https://your-host/payment/vnpay/ipn

set BANK_TRANSFER_ACCOUNT_NUMBER=1024520080
set BANK_TRANSFER_ACCOUNT_NAME=LE VAN TRIEU
set BANK_TRANSFER_BANK_NAME=Vietcombank
set BANK_TRANSFER_BANK_CODE=VCB
set BANK_TRANSFER_QR_URL=https://example.com/bank-qr.png
```

### 5. Initialize the database
Development uses `data/teetimevn_dev.db`. To (re)build it:

```powershell
python data/init_teetimevn_dev_sqlite.py
python data/create_bookings_table.py
python data/create_booking_status_history.py
python data/create_reviews_tables.py
python data/create_faq_tables.py
python data/init_static_page_i18n.py
python data/seed_ba_na_hills.py
python data/seed_faq.py
python data/seed_course_evaluations_upsert.py
python data/upgrade_booking_table_deposit.py
python data/upgrade_booking_table_flexible_cancel.py
python data/upgrade_owner_support.py
```

Supplemental scripts under `data/` keep canonical content fresh:
- `data/update_address*.py`, `data/update_overview*.py`, `data/update_course_evaluation.py`: bulk course metadata refreshers.
- `data/update_fx_rate.py`: ingestion for admin FX screens.
- `python data/"python update_maps_url.py"` and `data/new*_map.py`: coordinate/map sync utilities.
- `data/SEO/insert_SEO_*.py` (and the root copies) write localized SEO snippets to SQLite.

### 6. Run the development server
```powershell
set FLASK_APP=app.py
flask run --debug
```
or simply:
```powershell
python app.py
```
The root endpoint inspects `Accept-Language` and redirects to the best supported locale.

## Key Blueprints & Flows
- `modules/courses.py`: Catalog, filtering, SEO helpers, and shared DB accessors (`get_db`, `close_db`, `extract_city`).
- `modules/booking.py`: Booking wizard, tee-time availability API, optional services, cancellation/reschedule limits, deposit math, and booking status history logging.
- `modules/payments.py` & `modules/payment_vnpay.py`: VNPay return/IPN processing, signature verification, and bank-transfer fallbacks.
- `modules/admin.py`: Admin portal for courses, pricing tiers, FX rates, FAQs, SEO/i18n strings, reviews, bookings, and user CRUD (templates under `templates/admin/`).
- `modules/owner.py` & `modules/owner_support.py`: Partner-facing dashboards, booking detail views, and check-in helpers (templates under `templates/owner/`).
- `modules/auth.py`: Registration, login, password reset token flows, and Flask-Mail-powered notifications (`templates/auth/`).
- `modules/review.py`, `modules/faq.py`, `modules/fx.py`, `modules/news.py`, `modules/total_merit.py`: Supporting content/APIs exposed on localized routes.

## Booking, Payments, and Policies
- Config keys such as `BOOKING_CANCEL_WINDOW_HOURS`, `BOOKING_RESCHEDULE_WINDOW_HOURS`, `BOOKING_SLOT_CAPACITY`, and `BOOKING_DEPOSIT_PERCENT` drive enforcement in `modules/booking.py`.
- VNPay callbacks land on `/payment/vnpay/return` (browser) and `/payment/vnpay/ipn` (server-to-server). Successful deposits update balances via `_apply_successful_payment` inside `modules/payments.py`.
- Offline bank-transfer details render from the `BANK_TRANSFER_*` settings when guests choose that option.
- Schema upgrades (for example `data/upgrade_booking_table_deposit.py`, `data/upgrade_booking_table_flexible_cancel.py`) must be run whenever new columns are introduced.
- `docs/booking_flexibility.md` documents the recommended rollout/test plan for flexible cancellation and VNPay deposits.

## Internationalization Workflow
1. All localized routes prefix the URL with the language slug; supported values are defined in `SUPPORTED_URL_LANGS` within `app.py`.
2. Strings live in `translations/<locale>/LC_MESSAGES/messages.po`. Regenerate catalogs whenever templates or flashes change:
   ```powershell
   pybabel extract -F babel.cfg -o messages.pot .
   pybabel update -i messages.pot -d translations
   python tools/fill_missing_po.py
   pybabel compile -d translations
   ```
3. Use `i18n.sh` for a one-command workflow on Unix shells (or adapt it for PowerShell).
4. SEO/static copy lives in SQLite via `data/init_static_page_i18n.py` and the `data/SEO/insert_SEO_*.py` scripts.

## Admin & Owner Interfaces
- Admin URLs (`/<lang>/admin/…`) use components such as `templates/admin/dashboard.html`, `course_list.html`, `price_list.html`, `fx_list.html`, `faq_list.html`, `review_list.html`, and shared `_pagination.html`.
- Owner URLs (`/<lang>/owner/…`) render dashboards, booking tables, detail sheets, and check-in logs via `templates/owner/layout.html`, `dashboard.html`, `booking_list.html`, `booking_detail.html`, and `checkins.html`.

## Data & Content Utilities
- `data/list_course_vn.py`: quick course dumps for QA/partners.
- `data/clean_overview.py`: sanitizes course overview blobs before import.
- `data/seed_*` scripts (courses, FAQs, evaluations) populate demo datasets.
- `data/create_*` scripts create missing tables for bookings, reviews, FAQs, and status history.
- `data/upgrade_owner_support.py`: augments owner-side tables used by `modules/owner_support.py`.

## Static Assets & SEO
- Public templates (`templates/index.html`, `templates/courses.html`, `templates/course_detail.html`, `templates/booking.html`, `templates/faq.html`, `templates/booking_detail*.html`, `templates/sitemap.xml`, etc.) ensure localized content plus SEO metadata.
- `static/css/main.css` and peers control the front-end look and feel; update these assets when changing layouts.
- Routes in `app.py` serve `/sitemap.xml` (per-language course URLs) and `/robots.txt` (from `static/robots.txt`).

## Troubleshooting & Tips
- Restart the dev server after changing environment variables; `flask run --debug` only reloads on code edits.
- VNPay sandbox callbacks require a public tunnel (ngrok, Cloudflared) that forwards to `/payment/vnpay/ipn`.
- Gmail SMTP requires App Passwords; consider a dedicated provider (SendGrid, Mailgun) in production.
- Keep `messages.pot` and locale catalogs in sync; unresolved translations degrade the localized UX.
- No automated tests ship with the repo yet—exercise booking, payment, reschedule, and cancellation flows manually as described in `docs/booking_flexibility.md`.

