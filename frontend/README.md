# Smart Rental Tracking — frontend

React 18 + Vite 5, no router, no state library. One `styles.css`. All data goes
through `src/api.js`. See [`../HANDOFF.md`](../HANDOFF.md) for the full picture.

## Views

- **Customer view** — gated behind a login (`Login.jsx` / `Signup.jsx`; JWT in
  `localStorage`). `CustomerDashboard` shows `AlertsPanel` (flagged assets +
  pending SMS reminders) and an `AssetCard` grid. Calls
  `/customer/{id}/assets|alerts|sms-reminders` with `Authorization: Bearer` —
  the backend only ever returns the signed‑in customer's own data.
- **Dealer view** — open, no auth. `DealerDashboard`:
  - `DealerKpis` — 6 cards from `/dealer/summary`.
  - `RiskBreakdown` — CSS bar chart of customers per risk tier; click a bar to
    set the table filter.
  - Table — sort by column click, risk‑tier segmented filter, customer‑ID
    search. Click a row → `CustomerDrilldown` (stat strip + `AssetCard` grid
    from `/dealer/customer/{id}/assets` + that customer's activity slice); the
    back button restores the table's sort/filter/search.
  - `ActivityFeed` — read‑only timeline from `/dealer/activity-feed`
    (icon · date · type · message), styled to look unlike `AlertsPanel`.

## Run

```bash
# 1. backend (from repo root)
python backend/api/main.py            # http://127.0.0.1:8000

# 2. frontend (from frontend/)
npm install
npm run dev                           # http://localhost:5173
```

Override the API base with `VITE_API_BASE`, e.g.
`VITE_API_BASE=http://localhost:9000 npm run dev`.
