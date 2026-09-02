"""Stage 1 - rule-based anomaly flagging.

Input : rentals_unified.csv (via data_loader.load_rentals)
Output:
  * a per-rental-cycle table  (health_score, predicted anomaly flag, reasons)
  * one unified per-asset record per physical asset (schema.new_asset_record),
    built from the asset's *current* cycle (still-out cycle if any, else the
    latest cycle) plus a chronic-underutilisation check over recent history.

Only columns a dealer could actually observe are used as rule inputs.
``is_anomaly_ground_truth`` is read for evaluation only, never as a rule input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from ..config import AS_OF_DATE, STAGE1_RULES, type_config
from ..schema import new_asset_record


@dataclass(frozen=True)
class FiredRule:
    rule_id: str
    severity: str  # "hard" | "soft"
    weight: int
    reason: str


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def evaluate_cycle(row: dict, rules: dict = STAGE1_RULES) -> dict:
    """Evaluate one rental-cycle row.

    ``row`` is a plain dict (e.g. ``df.loc[i].to_dict()``) with the raw column
    names plus the derived ``idle_ratio`` / ``still_checked_out`` from
    data_loader.

    Returns a dict with:
      fired            : list[FiredRule]
      reasons          : list[str]
      health_score     : int in [0, 100]
      is_anomaly       : bool  (hard rule OR (high_idle AND severe_idle))
      hard_fired       : list[str] rule ids
    """
    w = rules["weights"]
    cfg = type_config(row["Type"])
    expected = cfg["expected_daily_hours"]
    idle_threshold = cfg["idle_threshold"]

    engine = float(row["Engine Hours/Day"])
    idle = float(row["Idle Hours/Day"])
    idle_ratio = row.get("idle_ratio")
    if idle_ratio is None or (isinstance(idle_ratio, float) and math.isnan(idle_ratio)):
        total = engine + idle
        idle_ratio = idle / total if total > 0 else 0.0

    still_out = bool(row["still_checked_out"])
    overdue = bool(row["is_overdue_now"])
    site_id = row.get("Site ID")
    operator_id = row.get("Last Operator ID")
    penalty_charged = bool(row["penalty_charged"])
    penalty_paid = row.get("penalty_paid")
    penalty_paid_is_false = penalty_paid is False  # <NA> / None -> not "paid"

    fired: list[FiredRule] = []

    # -- hard rules -------------------------------------------------------- #
    if still_out:
        exp_ret = row.get("Expected Return Date")
        tail = ""
        if isinstance(exp_ret, pd.Timestamp) and not pd.isna(exp_ret):
            days = (AS_OF_DATE - exp_ret.date()).days
            tail = (
                f" (expected {exp_ret.date()}, {days}d overdue)"
                if days > 0
                else f" (expected {exp_ret.date()})"
            )
        fired.append(
            FiredRule("still_checked_out", "hard", w["still_checked_out"],
                      f"Not returned - still checked out{tail}")
        )
    elif overdue:
        fired.append(
            FiredRule("overdue", "hard", w["overdue"], "Marked overdue")
        )

    if not site_id:
        fired.append(
            FiredRule("no_site", "hard", w["no_site"], "No site assigned")
        )
    if not operator_id:
        fired.append(
            FiredRule("no_operator", "hard", w["no_operator"],
                      "No operator assigned")
        )

    if penalty_charged and penalty_paid_is_false:
        fired.append(
            FiredRule("unpaid_penalty", "hard", w["unpaid_penalty"],
                      "Penalty charged and unpaid")
        )
    elif penalty_charged:
        fired.append(
            FiredRule("penalty_charged", "hard", w["penalty_charged"],
                      "Penalty charged")
        )

    # -- soft rules ------------------------------------------------------- #
    high_idle = idle_ratio > idle_threshold
    severe_idle = idle > rules["severe_idle_hours"]
    if high_idle:
        fired.append(
            FiredRule("high_idle", "soft", w["high_idle"],
                      f"High idle ratio ({_pct(idle_ratio)} > "
                      f"{_pct(idle_threshold)} threshold)")
        )
    if severe_idle:
        fired.append(
            FiredRule("severe_idle", "soft", w["severe_idle"],
                      f"Severe idle time ({idle:.1f} idle hrs/day)")
        )
    if engine < rules["low_util_fraction"] * expected:
        fired.append(
            FiredRule("low_utilization", "soft", w["low_utilization"],
                      f"Low utilization (engine {engine:.1f} hrs/day < "
                      f"{expected} expected)")
        )

    health = max(0, min(100, 100 - sum(f.weight for f in fired)))
    hard_fired = [f.rule_id for f in fired if f.severity == "hard"]
    is_anomaly = bool(hard_fired) or (high_idle and severe_idle)

    return {
        "fired": fired,
        "reasons": [f.reason for f in fired],
        "health_score": int(health),
        "is_anomaly": is_anomaly,
        "hard_fired": hard_fired,
    }


def _current_cycle_index(asset_rows: pd.DataFrame) -> int:
    """Row label of the asset's current cycle: the still-out cycle if one
    exists, otherwise the highest cycle_number."""
    still_out = asset_rows[asset_rows["still_checked_out"]]
    src = still_out if not still_out.empty else asset_rows
    return src["cycle_number"].idxmax()


def build_asset_record(asset_rows: pd.DataFrame, rules: dict = STAGE1_RULES) -> dict:
    """Collapse one physical asset's rental history into a unified record."""
    asset_rows = asset_rows.sort_values("cycle_number")
    cur_idx = _current_cycle_index(asset_rows)
    cur = asset_rows.loc[cur_idx].to_dict()
    result = evaluate_cycle(cur, rules)

    reasons = list(result["reasons"])

    # Chronic underutilisation: anomaly in >= chronic_min_flags of the last
    # chronic_lookback *completed* cycles (excludes the current cycle).
    completed = asset_rows[~asset_rows["still_checked_out"]]
    completed = completed[completed["cycle_number"] != cur["cycle_number"]]
    recent = completed.tail(rules["chronic_lookback"])
    if len(recent) >= rules["chronic_min_flags"]:
        flags = sum(evaluate_cycle(r.to_dict(), rules)["is_anomaly"]
                    for _, r in recent.iterrows())
        if flags >= rules["chronic_min_flags"]:
            reasons.append(
                f"Chronic underutilization (flagged in {flags} of last "
                f"{len(recent)} rentals)"
            )

    soft_ids = {f.rule_id for f in result["fired"] if f.severity == "soft"}
    available = not (cur["still_checked_out"] or bool(cur["is_overdue_now"]))
    reallocatable = (
        available
        and result["health_score"] <= rules["reallocatable_health_max"]
        and bool(soft_ids & {"high_idle", "severe_idle", "low_utilization"})
    )

    return new_asset_record(
        equipment_id=str(cur["Equipment ID"]),
        asset_type=str(cur["Type"]),
        customer_id=(None if cur["Customer ID"] is None
                     or (isinstance(cur["Customer ID"], float) and math.isnan(cur["Customer ID"]))
                     else str(cur["Customer ID"])),
        site_id=(cur["Site ID"] if cur["Site ID"] else None),
        health_score=result["health_score"],
        reasons=reasons,
        reallocatable=reallocatable,
    )


def run_stage1(df: pd.DataFrame, rules: dict = STAGE1_RULES):
    """Run Stage 1 over the whole unified frame.

    Returns ``(assets, rows_df)``:
      assets  : list[dict] - one unified record per physical asset
      rows_df : DataFrame  - per-rental-cycle detail incl. predicted flag,
                             for evaluation and the dealer dashboard.
    """
    row_records = []
    for _, row in df.iterrows():
        r = evaluate_cycle(row.to_dict(), rules)
        row_records.append(
            {
                "Equipment ID": row["Equipment ID"],
                "Type": row["Type"],
                "Customer ID": row["Customer ID"],
                "Site ID": row["Site ID"],
                "cycle_number": int(row["cycle_number"]),
                "health_score": r["health_score"],
                "is_anomaly_pred": r["is_anomaly"],
                "hard_rules": "|".join(r["hard_fired"]),
                "reasons": " | ".join(r["reasons"]),
                "is_anomaly_ground_truth": bool(row["is_anomaly_ground_truth"]),
            }
        )
    rows_df = pd.DataFrame(row_records)

    assets = [
        build_asset_record(g, rules)
        for _, g in df.groupby("Equipment ID", sort=True)
    ]
    return assets, rows_df


def evaluate_metrics(rows_df: pd.DataFrame) -> dict:
    """Precision / recall / F1 / accuracy of the predicted anomaly flag vs
    is_anomaly_ground_truth (row level)."""
    y_true = rows_df["is_anomaly_ground_truth"].to_numpy(dtype=bool)
    y_pred = rows_df["is_anomaly_pred"].to_numpy(dtype=bool)
    tp = int((y_true & y_pred).sum())
    fp = int((~y_true & y_pred).sum())
    fn = int((y_true & ~y_pred).sum())
    tn = int((~y_true & ~y_pred).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    accuracy = (tp + tn) / len(rows_df) if len(rows_df) else 0.0
    return {
        "n_rows": int(len(rows_df)),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }
