"""Thin readers over the pipeline's real output files.

Framework-agnostic: raises FileNotFoundError when an expected artifact is
missing (main.py turns that into a 503). Files are small (<=82 records), so
every call re-reads from disk - the API always reflects the latest pipeline run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data" / "processed"

PIPELINE_OUTPUT_JSON = DATA / "pipeline_output.json"
STAGE1_OUTPUT_CSV = DATA / "stage1_output.csv"
STAGE4_CUSTOMER_AGG_JSON = DATA / "stage4_customer_aggregate.json"
CUSTOMERS_CSV = DATA / "customers.csv"
ASSET_TYPE_CONFIG_JSON = REPO_ROOT / "data" / "raw" / "asset_type_config.json"

_HINT = {
    PIPELINE_OUTPUT_JSON: "python backend/stage4_matching/pipeline.py",
    STAGE1_OUTPUT_CSV: "python backend/stage1_rules/anomaly_flags.py",
    STAGE4_CUSTOMER_AGG_JSON: "python backend/stage4_matching/reallocation_engine.py",
    CUSTOMERS_CSV: "(ships with the repo)",
    ASSET_TYPE_CONFIG_JSON: "(ships with the repo)",
}


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.relative_to(REPO_ROOT)} not found - run: {_HINT.get(path, '?')}"
        )
    return path


# --------------------------------------------------------------------------- #
def load_pipeline_records() -> list[dict]:
    """Stage 1-4 per-asset records (Shared Contract shape)."""
    with open(_require(PIPELINE_OUTPUT_JSON), "r", encoding="utf-8") as fh:
        return json.load(fh)


def customer_ids() -> set[str]:
    """Valid customer ids, from customers.csv."""
    df = pd.read_csv(_require(CUSTOMERS_CSV), dtype=str)
    return set(df["Customer ID"].str.strip())


def assets_for_customer(customer_id: str) -> list[dict]:
    return [r for r in load_pipeline_records()
            if str(r.get("customer_id")) == customer_id]


def latest_cycle_is_flagged() -> dict[str, bool]:
    """{equipment_id: is_flagged} using each asset's latest cycle in
    stage1_output.csv."""
    df = pd.read_csv(_require(STAGE1_OUTPUT_CSV))
    latest = (df.sort_values("cycle_number")
              .groupby("Equipment ID").tail(1))
    return {str(e): bool(f)
            for e, f in zip(latest["Equipment ID"], latest["is_flagged"])}


def customers_table() -> dict[str, dict]:
    """{customer_id: {phone_number, reliability_score, risk_tier}} from
    customers.csv (dtype=str so '+91...' phone numbers keep their '+')."""
    df = pd.read_csv(_require(CUSTOMERS_CSV), dtype=str)
    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        cid = str(row["Customer ID"]).strip()
        rs = row.get("Reliability Score")
        out[cid] = {
            "phone_number": (row.get("Phone Number") or None),
            "reliability_score": (int(float(rs))
                                  if rs not in (None, "", "nan") and pd.notna(rs)
                                  else None),
            "risk_tier": (row.get("Risk Tier")
                          if row.get("Risk Tier") not in (None, "", "nan")
                          and pd.notna(row.get("Risk Tier")) else None),
        }
    return out


def customer_aggregate() -> list[dict]:
    """Stage 4 dealer-level per-customer aggregate (health avg + trend +
    renewal_risk)."""
    with open(_require(STAGE4_CUSTOMER_AGG_JSON), "r", encoding="utf-8") as fh:
        return json.load(fh)


def customer_aggregate_by_id() -> dict[str, dict]:
    return {c["customer_id"]: c for c in customer_aggregate()}


def asset_type_config() -> dict:
    """data/raw/asset_type_config.json - per-Type expected_daily_hours,
    idle_threshold and custom_fields. The frontend reads custom_fields from
    here to render type-specific fields without hardcoding them."""
    with open(_require(ASSET_TYPE_CONFIG_JSON), "r", encoding="utf-8") as fh:
        return json.load(fh)


def sms_reminders_for_customer(customer_id: str) -> list[dict]:
    """Pending return reminders for one customer, reusing the Stage 5
    sms_alerts logic (still-out rentals whose Expected Return Date is exactly
    `lead` days from that module's TODAY)."""
    stage5 = REPO_ROOT / "backend" / "stage5_customer_score"
    if str(stage5) not in sys.path:
        sys.path.insert(0, str(stage5))
    import sms_alerts  # noqa: E402

    due = sms_alerts.find_due_reminders()
    due = due[due["Customer ID"] == customer_id]
    out = []
    for _, row in due.iterrows():
        out.append({
            "customer_id": row["Customer ID"],
            "phone_number": row.get("Phone Number"),
            "equipment_id": row["Equipment ID"],
            "type": row["Type"],
            "site_id": (row["Site ID"] if pd.notna(row["Site ID"]) else None),
            "expected_return_date": str(
                pd.to_datetime(row["Expected Return Date"]).date()),
            "lead_days": int(row["lead_days"]),
            "risk_tier": row.get("Risk Tier"),
            "message": sms_alerts.build_message(row),
        })
    return out


def avg_health_by_customer() -> dict[str, float]:
    """Mean health_score over each customer's current assets in the pipeline
    output (the 'aggregated average health score from their assets')."""
    recs = load_pipeline_records()
    acc: dict[str, list[int]] = {}
    for r in recs:
        cid = str(r.get("customer_id"))
        hs = r.get("health_score")
        if hs is not None:
            acc.setdefault(cid, []).append(hs)
    return {cid: round(sum(v) / len(v), 1) for cid, v in acc.items()}


def assets_count_by_customer() -> dict[str, int]:
    recs = load_pipeline_records()
    out: dict[str, int] = {}
    for r in recs:
        out[str(r.get("customer_id"))] = out.get(str(r.get("customer_id")), 0) + 1
    return out
