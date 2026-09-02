"""End-to-end pipeline: Stage 1 + 2 + 3 + 4 -> final per-asset JSON.

Produces one record per physical asset (its latest cycle) in the Shared
Contract shape:

    {
      "equipment_id", "type", "customer_id", "site_id",
      "health_score",            # Stage 1  (rule-based, current cycle)
      "reasons",                 # Stage 1
      "reallocatable",           # Stage 3  (ML flag)
      "demand_forecast",         # Stage 2  {site_id, type, predicted_need_days}
      "recommendation"           # Stage 4  {action, from_site, to_site, reason} or null
    }

demand_forecast points at the site (among the asset's customer's sites) that is
forecast to want this Type the most - which is why, for a recommended move,
demand_forecast.site_id matches recommendation.to_site.

Run:
    python backend/stage4_matching/pipeline.py            # use existing stage outputs
    python backend/stage4_matching/pipeline.py --rebuild  # regenerate stage 1/2/3 first
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (
    str(REPO_ROOT),
    str(REPO_ROOT / "backend" / "stage1_rules"),
    str(REPO_ROOT / "backend" / "stage2_forecasting"),
    str(REPO_ROOT / "backend" / "stage3_scoring"),
    str(HERE),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from forecast import forecast_demand  # noqa: E402
from reallocation_engine import (  # noqa: E402
    FORECAST_HORIZON_DAYS,
    _customer_site_map,
    customer_health_aggregate,
    latest_cycle_state,
    recommend_reallocations,
)
from src.schema import new_asset_record, validate_record  # noqa: E402

STAGE1_OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage1_output.csv"
STAGE2_MODEL_JSON = REPO_ROOT / "data" / "processed" / "stage2_demand_model.json"
STAGE3_OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage3_output.csv"
PIPELINE_OUTPUT_JSON = REPO_ROOT / "data" / "processed" / "pipeline_output.json"


def ensure_upstream(rebuild: bool = False) -> None:
    """Make sure Stage 1/2/3 artifacts exist (optionally force a rebuild)."""
    if rebuild or not STAGE1_OUTPUT_CSV.exists():
        import anomaly_flags
        anomaly_flags.main()
    if rebuild or not STAGE2_MODEL_JSON.exists():
        import train_holt_winters
        train_holt_winters.main()
    if rebuild or not STAGE3_OUTPUT_CSV.exists():
        import train_classifier
        train_classifier.main()


def run_pipeline(horizon_days: int = FORECAST_HORIZON_DAYS) -> list[dict]:
    state = latest_cycle_state()
    sites_by_customer = _customer_site_map(state)
    recs_by_asset = {
        r["equipment_id"]: r["recommendation"]
        for r in recommend_reallocations(state, horizon_days)
    }

    records: list[dict] = []
    for _, row in state.iterrows():
        eq = str(row["Equipment ID"])
        typ = str(row["Type"])
        cust = None if pd.isna(row["Customer ID"]) else str(row["Customer ID"])
        site = None if pd.isna(row["Site ID"]) else str(row["Site ID"])

        # Stage 2: most-wanted site for this Type among the customer's sites.
        cand_sites = sites_by_customer.get(cust, [site] if site else [])
        demand_block = None
        if cand_sites:
            best = max((forecast_demand(s, typ, horizon_days) for s in cand_sites),
                       key=lambda f: f["predicted_need_score"])
            demand_block = {
                "site_id": best["site_id"],
                "type": typ,
                "predicted_need_days": best["predicted_need_days"],
            }

        realloc = row.get("reallocatable_flag")
        rec = new_asset_record(
            equipment_id=eq,
            asset_type=typ,
            customer_id=cust,
            site_id=site,
            health_score=int(row["health_score"]),
            reasons=list(row["s1_reasons"]),
            reallocatable=(None if pd.isna(realloc) else bool(realloc)),
            demand_forecast=demand_block,
            recommendation=recs_by_asset.get(eq),
        )
        validate_record(rec)
        records.append(rec)

    records.sort(key=lambda r: r["equipment_id"])
    return records


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    ensure_upstream(rebuild=rebuild)

    records = run_pipeline()
    PIPELINE_OUTPUT_JSON.write_text(json.dumps(records, indent=2))

    n_reason = sum(1 for r in records if r["reasons"])
    n_realloc = sum(1 for r in records if r["reallocatable"])
    n_rec = sum(1 for r in records if r["recommendation"])
    agg = customer_health_aggregate()
    n_risk = sum(a["renewal_risk"] for a in agg)

    print("=" * 78)
    print("PIPELINE  (Stage 1 -> 2 -> 3 -> 4)")
    print("=" * 78)
    print(f"asset records written : {len(records)}  -> "
          f"{PIPELINE_OUTPUT_JSON.relative_to(REPO_ROOT)}")
    print(f"  with >=1 reason      : {n_reason}")
    print(f"  reallocatable (S3)   : {n_realloc}")
    print(f"  with a recommendation: {n_rec}")
    print(f"  renewal_risk custs   : {n_risk}/{len(agg)}")

    sample = next((r for r in records if r["recommendation"]), records[0])
    print("\nsample record with a recommendation:")
    print(json.dumps(sample, indent=2))


if __name__ == "__main__":
    main()
