# Smart Rental Tracking — Handoff / Architecture Guide

Everything you need to run the project, understand what is already built, and add
new features. `README.md` is the original brief and still holds the detailed
Stage 1 rule reference; this file is the current, whole‑system picture.

Last updated: after the dealer‑dashboard drill‑down work (see
[Change log](#change-log-what-this-session-added)).

---

## 1. What it is

A rental‑equipment tracking platform for Caterpillar dealers, with the dealer's
customers as end users. One unified dataset flows through a five‑stage pipeline
into a FastAPI backend and a React (Vite) frontend with two views: **customer**
(authenticated, sees only their own fleet) and **dealer** (open, sees everyone).

```
data/processed/rentals_unified.csv  (826 rental cycles · 82 assets · 18 customers)
      │
      ├─ Stage 1  rule-based anomaly flags          backend/stage1_rules/
      ├─ Stage 2  Holt / demand forecasting          backend/stage2_forecasting/
      ├─ Stage 3  "reallocatable" RF classifier      backend/stage3_scoring/
      ├─ Stage 4  reallocation matching engine       backend/stage4_matching/
      └─ Stage 5  customer reliability + SMS alerts   backend/stage5_customer_score/
      │
      ▼  data/processed/pipeline_output.json  +  customers.csv (scores filled)
      │
   FastAPI  backend/api/   ──►   React + Vite  frontend/
```

All five stages are **built and committed**. Model artifacts (`*.pkl`,
`*_meta.json`) and every `data/processed/*` file are checked in, so the API runs
without re‑training anything.

---

## 2. Quick start

### Prerequisites
| Tool | Version used here | Notes |
|------|-------------------|-------|
| Python | 3.14 | 3.11+ should be fine |
| Node | 24 | 18+ fine |
| npm | 11 | |

### Backend

```bash
pip install -r requirements.txt
python backend/api/main.py            # http://127.0.0.1:8000  · docs at /docs
```

CORS is wide open for local dev. The API reads the committed
`data/processed/*` files on every request, so it works immediately.

### Frontend

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

Point the frontend at a non‑default API with `VITE_API_BASE`, e.g.
`VITE_API_BASE=http://localhost:9000 npm run dev`.

### Regenerate pipeline outputs (only if you change a stage)

```bash
python scripts/run_all.py             # runs every stage in its own process, in order
```

Each stage also runs standalone, e.g. `python backend/stage1_rules/anomaly_flags.py`.

### Tests

```bash
pytest -q                             # 40 tests: test_stage1 / test_auth / test_dealer
```

`test_auth.py` and `test_dealer.py` spin up the FastAPI app with
`fastapi.testclient.TestClient` and hit it against the real committed data.
`test_auth.py` monkeypatches the account‑store path to a tmp file so signups
don't touch `data/processed/`.

---

## 3. Repo layout

```
src/                         Stage 1 reference implementation + frozen record schema
  config.py                  paths, asset-type config, STAGE1_RULES weights, AS_OF_DATE
  schema.py                  new_asset_record() / validate_record()
  data_loader.py             typed CSV loaders
  stages/stage1.py           evaluate_cycle(), build_asset_record(), run_stage1(), metrics

backend/
  stage1_rules/anomaly_flags.py        Stage 1 runner  -> data/processed/stage1_output.csv
  stage2_forecasting/                   Holt forecasting -> stage2_demand_model.json
  stage3_scoring/                       RF "reallocatable" -> stage3_output.csv + model.pkl
  stage4_matching/
    reallocation_engine.py             -> stage4_recommendations*.json, stage4_customer_aggregate.json
    pipeline.py                        stitches 1..4 -> data/processed/pipeline_output.json
  stage5_customer_score/
    train_classifier.py                -> customers.csv (Reliability Score / Risk Tier), model.pkl
    sms_alerts.py                      return-reminder logic (TODAY pinned to 2025-11-23)
  api/
    main.py                            FastAPI app, CORS, 503-on-missing-artifact handler
    data_access.py                     ALL file reads live here (framework-agnostic)
    schemas.py                         Pydantic response/request models
    auth.py                            hashing + JWT + CSV account store + /auth routes + dependency
    customer_routes.py                 /customer/*  (bearer token, own-data-only)
    dealer_routes.py                   /dealer/*    (open, no auth)

frontend/src/
  api.js                     fetch wrapper, token storage, one method per endpoint
  App.jsx                    view toggle + auth gate for the customer view + logout
  components/
    Login.jsx  Signup.jsx    email/password auth forms
    CustomerDashboard.jsx    AlertsPanel + AssetCard grid
    AlertsPanel.jsx          flagged assets + pending SMS reminders
    AssetCard.jsx            one asset (Shared Contract shape + custom_fields)
    DealerDashboard.jsx      KPIs + RiskBreakdown + table (sort/filter/search) + ActivityFeed
    DealerKpis.jsx           6 KPI cards from /dealer/summary
    RiskBreakdown.jsx        CSS bar chart of customers per risk tier (click = set filter)
    CustomerDrilldown.jsx    per-customer detail: stat strip + AssetCard grid + activity slice
    ActivityFeed.jsx         read-only timeline (icon · date · type · message)
  styles.css                 single stylesheet, CSS custom properties at the top

scripts/run_all.py           run the whole pipeline end to end
tests/                       test_stage1.py, test_auth.py, test_dealer.py
```

**Convention that matters:** the API never reads a CSV/JSON directly in a route —
every file access goes through a named function in `backend/api/data_access.py`.
Add an accessor there, not `pd.read_csv` in `*_routes.py`.

---

## 4. The Shared Contract (per‑asset record)

Every stage after Stage 1 produces/consumes this exact shape. Unset fields are
`null`, never omitted. `AssetRecord` in `schemas.py` mirrors it, so using it as a
`response_model` also validates the contract.

```json
{
  "equipment_id": "EQX1004",
  "type": "Crane",
  "customer_id": "CUST14",
  "site_id": "S002",
  "health_score": 55,
  "reasons": ["High idle ratio (76% > 50% threshold)", "Severe idle time (11.3 idle hrs/day)"],
  "reallocatable": true,
  "demand_forecast": { "site_id": "S002", "type": "Crane", "predicted_need_days": 9 },
  "recommendation": { "action": "move", "from_site": "S002", "to_site": "S005", "reason": "…" }
}
```

`pipeline_output.json` is a list of 82 of these. `data_access.load_pipeline_records()`
returns it.

---

## 5. API reference

Base URL `http://127.0.0.1:8000`. Interactive docs at `/docs`.

### Meta
| Method | Path | Notes |
|--------|------|-------|
| GET | `/` | service info + endpoint list |
| GET | `/health` | `{"status":"ok"}` |
| GET | `/config/asset-types` | `data/raw/asset_type_config.json` — per‑Type `expected_daily_hours`, `idle_threshold`, `custom_fields` |

### Auth  (`backend/api/auth.py`)
| Method | Path | Body / query | Returns |
|--------|------|--------------|---------|
| POST | `/auth/signup` | `{email, password, customer_id}` | `201 {"message":"account created"}` — 400 if `customer_id` not in `customers.csv`, 409 if email or customer_id already registered |
| POST | `/auth/login` | `{email, password}` | `{access_token, token_type:"bearer", customer_id}` — `401 "invalid credentials"` on any failure (does not reveal which half was wrong) |
| GET | `/auth/check-email` | `?email=` | `{"exists": bool}` — UX hint only; used by the login form to say "no account yet, sign up?" vs "wrong password". Never gate real logic on this. |

### Customer  (`backend/api/customer_routes.py`) — **Bearer token required, own data only**
Every route: `Depends(auth.get_current_customer)` decodes the JWT → `customer_id`;
if the path `{customer_id}` ≠ the token's, it's **403 "you can only access your own data"**
(checked before the existence check so it can't enumerate IDs).

| Method | Path | Returns |
|--------|------|---------|
| GET | `/customer/{customer_id}/assets` | `list[AssetRecord]` for that customer, from `pipeline_output.json` |
| GET | `/customer/{customer_id}/alerts` | same, filtered to assets whose latest Stage 1 cycle is `is_flagged` |
| GET | `/customer/{customer_id}/sms-reminders` | pending return reminders (Stage 5 `sms_alerts.find_due_reminders`) |

### Dealer  (`backend/api/dealer_routes.py`) — **no auth (by design)**
| Method | Path | Returns |
|--------|------|---------|
| GET | `/dealer/customers` | `list[DealerCustomer]` — id, phone, reliability, risk_tier, n_assets, avg_health_score, trend, renewal_risk |
| GET | `/dealer/customers/{customer_id}` | `DealerCustomerDetail` — the aggregate above **+ embedded `assets` list**; 404 for unknown id |
| GET | `/dealer/customer/{customer_id}/assets` | `list[AssetRecord]` — same per‑asset shape as the customer route, dealer side. Note the **singular** `customer`. 404 for unknown id |
| GET | `/dealer/summary` | `SummaryStats` — `total_customers, total_assets, avg_fleet_health_score, high_risk_count, pending_sms_count, unpaid_penalty_count` |
| GET | `/dealer/renewal-risk` | `list[RenewalRiskCustomer]` — customers flagged `renewal_risk` in Stage 4's aggregate |
| GET | `/dealer/activity-feed` | `list[ActivityEvent]` — top 50, newest first. See below |

**`ActivityEvent` = `{date, type, customer_id, message}`.** It is a *retroactive
reconstruction*, not a live log — `data_access.activity_events()` rebuilds it on
each call from four dated sources:

| `type` | one per | dated by |
|--------|---------|----------|
| `high_risk` | customer with `risk_tier == "High"` | their most recent `Check-Out Date` |
| `flag` | Stage 1 `is_flagged` row | that row's `Check-Out Date` |
| `penalty` | `penalty_charged == True` row | `Expected Return Date` |
| `sms_reminder` | pending Stage 5 reminder | trigger date = `Expected Return Date − lead_days` |

Missing artifacts → the app‑wide handler in `main.py` returns **503** with the
command that regenerates the file.

---

## 6. Authentication — how it works

- **Hashing:** `passlib` `CryptContext(schemes=["bcrypt"])`.
- **⚠️ Version pin:** `requirements.txt` pins `bcrypt>=4.0,<4.1`. passlib 1.7.4
  crashes on bcrypt ≥ 4.1 / 5.x (`ValueError: password cannot be longer than 72
  bytes` during its self‑test). If you bump it, test signup/login immediately.
- **Tokens:** `python-jose[cryptography]`, HS256, `sub = customer_id`, 60‑minute
  expiry (`create_access_token(customer_id, expires_minutes=60)`).
- **Secret:** `os.environ["RENTAL_JWT_SECRET"]`, with an insecure hard‑coded dev
  fallback. **Set the env var for any real deployment.**
- **Account store:** `data/processed/customer_accounts.csv`
  (`email, hashed_password, customer_id, created_at`). **Git‑ignored** — created
  on first signup. Uniqueness (email + customer_id) is enforced under a
  `threading.Lock` in `data_access`‑adjacent helpers in `auth.py`.
- **Signup rule:** you can only link a login to a `customer_id` that already
  exists in `customers.csv` — the whole pipeline is scoped to IDs with rental
  history, so arbitrary new customers are rejected (400).
- **Dependency:** `auth.get_current_customer` (uses
  `OAuth2PasswordBearer(tokenUrl="/auth/login")`) → returns the `customer_id`
  claim, 401 on missing/expired/garbage token.
- **Dealer side is intentionally unauthenticated.** If you add dealer auth,
  it's a separate concern from the customer flow.

### Frontend auth
- `frontend/src/api.js` stores the JWT + customer_id in `localStorage`
  (`rental_tracker_token`, `rental_tracker_customer_id`).
- Customer API calls send `Authorization: Bearer <token>`; a 401 clears the
  token and calls the handler `App.jsx` registered → bounces to `Login`.
- `App.jsx` gates the **customer view** behind a token; the **dealer view** is
  always reachable. Signup does **not** auto‑login (two‑step by design).

---

## 7. Frontend notes

- **No router.** `App.jsx` holds `view` (`'customer'|'dealer'`) plus the auth
  session; sub‑views (e.g. the dealer drill‑down) are conditional renders inside
  their component.
- **No state library.** Plain `useState`/`useMemo`. `api.js` is the only data
  layer.
- **Styling:** one `styles.css`, CSS custom properties (`--panel`, `--line`,
  `--good/--warn/--bad`, …) at the top. Reuse `.chip`, `.card`, `.grid`,
  `.pill`, `.banner` rather than adding component CSS where possible.
- **`AssetCard.jsx`** renders the Shared Contract shape and takes a
  `customFields` string[] (from `/config/asset-types` → `custom_fields`) so it
  never hardcodes per‑Type fields. `AssetRecord` doesn't carry custom‑field
  *values*, so they render as "—" on both customer and dealer sides — that's
  expected, not a bug.
- **Dealer table state** (`sort`, `tier`, `query`) lives in `DealerDashboard`;
  the drill‑down is a sibling render, so opening/closing it never disturbs the
  table.

---

## 8. Data gotchas

| Thing | Value | Why it matters |
|-------|-------|----------------|
| Effective "today" for historical data | **2025‑12‑31** (`src/config.py` `AS_OF_DATE`) | overdue / still‑out logic |
| SMS reminder "today" | **2025‑11‑23** (`sms_alerts.py` `TODAY`) | `find_due_reminders()` only returns reminders whose lead date lands exactly on this — usually 1 row (CUST01 / EQX1063) |
| `is_anomaly_ground_truth` | eval only | never a rule/model input |
| `gap_days_to_next_checkout` | Stage 3's label | not an input feature |
| `stage1_output.csv` still‑out rows | 33 of 826 have blank `Actual Check-In Date` | date helpers fall back to Expected Return / Check‑Out |
| Stage 3 / Stage 5 models | weak signal on this tiny dataset | Stage 5 falls back to the rule score when the model has no signal; documented, not a bug |
| Line endings | repo has no `.gitattributes` | Git warns `LF will be replaced by CRLF` on Windows — harmless |

---

## 9. Change log — what this session added

Starting point (`c66771f`): full 5‑stage pipeline + FastAPI + a basic
customer/dealer frontend, **no auth**, dealer view was a plain sortable table.

| Commits | What |
|---------|------|
| `ea10f5c` → `acfb2d2` → `98289c2` | **Customer auth.** `auth.py` (passlib bcrypt + jose JWT + CSV account store + `/auth/signup`,`/auth/login` + `get_current_customer`). `customer_routes.py` now requires a token and 403s on another customer's id. `tests/test_auth.py`. Consolidated from an initial 3‑file split into one `auth.py`. |
| `ac60feb` | **Frontend auth.** `Login.jsx` + `Signup.jsx`, token in `localStorage`, `Authorization` header on customer calls, logout in the topbar, customer view gated behind a token. |
| `5745e4c` | **`GET /auth/check-email`** + a friendlier "no account yet — sign up?" path on failed login (pre‑fills the signup email). |
| `0503cbb` | **Dealer dashboard upgrade.** KPI cards, risk‑tier filter + customer search on the table, `RiskBreakdown` bar chart, click‑a‑row drill‑down, first activity feed. New: `DealerKpis`, `RiskBreakdown`, `CustomerDrilldown`, `ActivityFeed`, `/dealer/customers/{id}`, `/dealer/activity` (later reshaped). `tests/test_dealer.py`. |
| `857f3d7` | **`/dealer/summary`** (`SummaryStats`) + **`/dealer/activity-feed`** reshaped to `{date,type,message,customer_id}`, top 50, 4 sources incl. High‑risk‑customer events + **`/dealer/customer/{id}/assets`**. `data_access.penalty_charged_records()` / `unpaid_penalty_count()`. |
| `3478b71` | Dealer KPI cards trimmed to the 6 named metrics; tier filter reordered All/Low/Medium/High; search scoped to `customer_id`. |
| `eee5ed4` | `ActivityFeed` stripped to a **read‑only timeline** (icon · date · type · message), styled distinct from `AlertsPanel`. |
| _this commit_ | Dealer table row → drill‑down now fetches **`/dealer/customer/{id}/assets`** and renders the assets with the **`AssetCard` grid** (same as `CustomerDashboard`), not a plain table. `assetTypes` fetched in `DealerDashboard` and passed down for `custom_fields`. Back button preserves table sort/filter/search. |

40 tests pass throughout.

---

## 10. Known limitations / good first improvements

- **No `/auth/me`** — it was removed. A stored token is trusted on load and only
  invalidated when a real call returns 401. Re‑add a lightweight `/auth/me`
  (uses `get_current_customer`) if you want eager validation on refresh.
- **Dealer side has no auth.** Fine for a demo; add a dealer login if this goes
  further.
- **Activity feed is capped at 50 and has no paging/filtering** (deliberately
  read‑only). `data_access.activity_events(limit=...)` already takes a limit if
  you want more.
- **Custom‑field values aren't in `AssetRecord`** — see §7. Widen the model +
  `pipeline.py` output if the dealer needs real spec values.
- **Stage 3/5 models are weak** on 826 rows — don't over‑trust `reallocatable`
  / reliability precision. Documented in `README.md`.
- **SMS is a stub** (`sms_alerts.send_sms` just prints). Real Twilio wiring is
  sketched in a comment there.
- **`data/processed/*` is committed** so the API runs cold, but that means a
  pipeline change requires re‑running `scripts/run_all.py` and committing the
  regenerated files. `model_meta.json` `trained_at` timestamps churn on every
  retrain — check those diffs before committing.

---

## 11. How to add a feature

### A new dealer metric / endpoint
1. Add a reader to `backend/api/data_access.py` (never `pd.read_csv` in a route).
2. Add a `response_model` to `backend/api/schemas.py`.
3. Add the route to `backend/api/dealer_routes.py` and list it in `main.py`'s `/`.
4. Add `api.<name>()` to `frontend/src/api.js`.
5. Consume it in a component; reuse `.chip`/`.card`/`.kpi-card`/`.grid` styles.
6. Add a case to `tests/test_dealer.py` (TestClient + real data).

### A new customer‑facing endpoint
Same, but in `customer_routes.py`, add
`caller_id: str = Depends(auth.get_current_customer)` and the
`if customer_id != caller_id: 403` guard (copy an existing route). Cover it in
`tests/test_auth.py`.

### A new pipeline signal
Add/extend a stage under `backend/stage*/`, wire it into
`backend/stage4_matching/pipeline.py` so it lands in `pipeline_output.json`
(and/or `schemas.AssetRecord`), re‑run `python scripts/run_all.py`, commit the
regenerated `data/processed/*` + model files, and extend
`tests/test_stage1.py`'s dataset regression guard if it changes Stage 1 metrics.

### Frontend‑only view
`App.jsx` switches on `view`. For a sub‑view within a dashboard, follow
`DealerDashboard` → `CustomerDrilldown`: keep list state in the parent, render
the detail as a sibling branch, pass an `onBack` callback.
