# Smart Rental Tracking - frontend

Two views over the pipeline's FastAPI backend.

- **Customer view** - `/customer/{id}/assets`, `/customer/{id}/alerts`,
  `/customer/{id}/sms-reminders`. Asset cards (Equipment ID, Type, health score,
  reasons on hover / click, a "→ Move to Site X" button when the asset is
  reallocatable with a target), plus an alerts panel (flagged assets + pending
  SMS reminders). `AssetCard.jsx` renders the type-specific extra fields from
  `/config/asset-types` (`custom_fields` in `data/raw/asset_type_config.json`) -
  no field names are hardcoded per Type.
- **Dealer view** - `/dealer/customers`, `/dealer/renewal-risk`. Sortable table
  (Customer ID, Reliability Score, Risk Tier, avg health, health trend, assets);
  renewal-risk customers are highlighted.

## Run

```bash
# 1. backend (from repo root)
python backend/api/main.py            # http://127.0.0.1:8000

# 2. frontend (from frontend/)
npm install
npm run dev                           # http://localhost:5173
```

If the API is hosted elsewhere, set `VITE_API_BASE`, e.g.
`VITE_API_BASE=http://localhost:9000 npm run dev`.
