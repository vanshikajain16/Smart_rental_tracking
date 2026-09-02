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


# --------------------------------------------------------------------------- #
# Dealer drill-down + retroactive activity feed
# --------------------------------------------------------------------------- #
def dealer_customer_detail(customer_id: str) -> dict:
    """One customer's row-level aggregate plus their current per-asset records
    (reuses assets_for_customer). Powers the dealer dashboard drill-down."""
    agg = customer_aggregate_by_id().get(customer_id, {})
    table = customers_table().get(customer_id, {})
    assets = assets_for_customer(customer_id)
    return {
        "customer_id": customer_id,
        "phone_number": table.get("phone_number") or agg.get("phone_number"),
        "reliability_score": table.get("reliability_score"),
        "risk_tier": table.get("risk_tier"),
        "n_assets": len(assets),
        "avg_health_score": avg_health_by_customer().get(
            customer_id, agg.get("avg_health_score")),
        "avg_health_all_cycles": agg.get("avg_health_all_cycles"),
        "n_cycles_observed": agg.get("n_cycles_observed"),
        "trend_direction": agg.get("trend_direction"),
        "health_trend_slope_per_month": agg.get("health_trend_slope_per_month"),
        "renewal_risk": bool(agg.get("renewal_risk", False)),
        "assets": assets,
    }


def _due_sms_reminders() -> list[dict]:
    """Every pending Stage 5 reminder in one find_due_reminders() call."""
    stage5 = REPO_ROOT / "backend" / "stage5_customer_score"
    if str(stage5) not in sys.path:
        sys.path.insert(0, str(stage5))
    import sms_alerts  # noqa: E402

    out = []
    for _, row in sms_alerts.find_due_reminders().iterrows():
        out.append({
            "customer_id": str(row["Customer ID"]).strip(),
            "equipment_id": row["Equipment ID"],
            "expected_return_date": str(
                pd.to_datetime(row["Expected Return Date"]).date()),
            "lead_days": int(row["lead_days"]),
        })
    return out


def activity_events(customer_id: str | None = None,
                    limit: int | None = None) -> list[dict]:
    """A retroactive activity feed - NOT a live log. One-shot reconstruction,
    newest first, from dated records that already exist:

      * Stage 1 flags        (is_flagged rows in stage1_output.csv)
      * penalty_charged rows  (same file)
      * pending SMS reminders (Stage 5 find_due_reminders)

    Each cycle row is dated by its Actual Check-In Date, falling back to the
    Expected Return / Check-In / Check-Out date when a rental is still out.
    """
    df = pd.read_csv(_require(STAGE1_OUTPUT_CSV), dtype=str)

    def _is_true(v: object) -> bool:
        return str(v).strip().lower() == "true"

    def _event_date(row: pd.Series) -> str | None:
        for col in ("Actual Check-In Date", "Expected Return Date",
                    "Check-In Date", "Check-Out Date"):
            v = row.get(col)
            if v is not None and str(v).strip().lower() not in ("", "nan", "nat"):
                try:
                    return str(pd.to_datetime(v).date())
                except (ValueError, TypeError):
                    continue
        return None

    events: list[dict] = []
    for _, row in df.iterrows():
        cid = str(row.get("Customer ID", "")).strip()
        if customer_id and cid != customer_id:
            continue
        when = _event_date(row)
        if when is None:
            continue
        eq = row.get("Equipment ID")
        if _is_true(row.get("is_flagged")):
            reasons = (row.get("reasons") or "").strip()
            events.append({
                "date": when, "customer_id": cid, "equipment_id": eq,
                "category": "flag",
                "summary": f"{eq} flagged" + (f": {reasons}" if reasons else ""),
            })
        if _is_true(row.get("penalty_charged")):
            paid = _is_true(row.get("penalty_paid"))
            events.append({
                "date": when, "customer_id": cid, "equipment_id": eq,
                "category": "penalty",
                "summary": (f"Penalty charged on {eq} "
                            + ("(paid)" if paid else "(unpaid)")),
            })

    for rem in _due_sms_reminders():
        if customer_id and rem["customer_id"] != customer_id:
            continue
        erd = pd.to_datetime(rem["expected_return_date"]).date()
        send = str(erd - pd.Timedelta(days=int(rem["lead_days"])))
        events.append({
            "date": send, "customer_id": rem["customer_id"],
            "equipment_id": rem["equipment_id"], "category": "sms_reminder",
            "summary": (f"Return reminder queued for {rem['equipment_id']} "
                        f"(due {rem['expected_return_date']})"),
        })

    events.sort(
        key=lambda e: (e["date"], e["category"], str(e["equipment_id"])),
        reverse=True,
    )
    return events[:limit] if limit else events
