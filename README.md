# Smart Rental Tracking System

Rental-equipment tracking platform for Caterpillar dealers, with the dealer's
customers as end users. One unified dataset flows through a five-stage pipeline
into an API and a dual (customer / dealer) dashboard.

```
Raw data
  -> Stage 1  rule-based anomaly flags          [built]
  -> Stage 2  ML demand forecasting             [todo]
  -> Stage 3  ML underutilization scoring       [todo]
  -> Stage 4  reallocation matching engine      [todo]
  -> Stage 5  customer reliability scoring      [todo]
  -> SMS alerts -> API -> dual dashboard        [todo]
```

## Data

| File | Rows | Notes |
|------|------|-------|
| `data/processed/rentals_unified.csv` | 826 | 82 physical assets, ~10 rental cycles each over 2025. One row = one rental cycle. |
| `data/processed/customers.csv` | 18 | `Reliability Score` / `Risk Tier` filled by Stage 5. |
| `data/raw/asset_type_config.json` | 5 types | `expected_daily_hours`, `idle_threshold`, `custom_fields` per Type. |

`is_anomaly_ground_truth` is for evaluation only and is never a model / rule input.
`gap_days_to_next_checkout` is Stage 3's label. Effective "today" for the
historical data is **2025-12-31** (`config.AS_OF_DATE`).

## Unified per-asset record

Every stage after Stage 1 produces / consumes this exact shape (see
`src/schema.py`). Unpopulated fields are `null`, never omitted.

```json
{
  "equipment_id": "EQX1004",
  "type": "Crane",
  "customer_id": "CUST14",
  "site_id": "S002",
  "health_score": 55,
  "reasons": ["High idle ratio (76% > 50% threshold)", "Severe idle time (11.3 idle hrs/day)"],
  "reallocatable": true,
  "demand_forecast": null,
  "recommendation": null
}
```

## Layout

```
src/
  config.py          paths, asset-type config, STAGE1_RULES (all tunables)
  schema.py          new_asset_record() + validate_record() for the frozen shape
  data_loader.py     typed loaders (dates, nullable bools, row ordering)
  stages/stage1.py   evaluate_cycle(), build_asset_record(), run_stage1(), metrics
scripts/
  run_stage1.py      run Stage 1, write outputs, print evaluation
tests/
  test_stage1.py     unit rules + schema + dataset regression guard
```

## Stage 1 - rule-based anomaly flags

`evaluate_cycle()` scores one rental cycle. `health_score = clamp(100 - sum of
fired-rule weights, 0, 100)`.

**Hard rules** (each makes the cycle an anomaly on its own - these are the
deterministic drivers of the ground-truth label):

| Rule | Condition | Weight |
|------|-----------|-------:|
| `still_checked_out` | `Actual Check-In Date` is null | 45 |
| `overdue` | `is_overdue_now` | 40 |
| `no_site` | `Site ID` missing | 20 |
| `no_operator` | `Last Operator ID` missing | 20 |
| `unpaid_penalty` | `penalty_charged` and not `penalty_paid` | 30 |
| `penalty_charged` | `penalty_charged` (paid / unknown) | 15 |

**Soft rules** (dent the health score; flag an anomaly only when `high_idle` and
`severe_idle` fire together):

| Rule | Condition | Weight |
|------|-----------|-------:|
| `high_idle` | `idle_ratio > type.idle_threshold` | 25 |
| `severe_idle` | `Idle Hours/Day > 8.5` | 20 |
| `low_utilization` | `Engine Hours/Day < 0.5 * type.expected_daily_hours` | 15 |

`build_asset_record()` collapses an asset's history to one record using its
**current cycle** (the still-out cycle if any, else the latest `cycle_number`),
adds a *chronic underutilization* reason when >=2 of the last 3 completed cycles
were anomalies, and sets `reallocatable` when the asset is physically available
(not still out / overdue), `health_score <= 60`, and a soft idle/utilization
rule fired.

### Run

```bash
pip install -r requirements.txt
python scripts/run_stage1.py
```

Outputs `data/processed/stage1_rows.csv` (per-cycle detail for evaluation and
the dealer view) and `data/processed/stage1_assets.json` (82 unified records).

### Current evaluation (row-level, vs `is_anomaly_ground_truth`)

| precision | recall | F1 | accuracy |
|-----------|--------|-----|----------|
| 0.92 | 0.90 | 0.91 | 0.98 |

```bash
pytest -q
```
