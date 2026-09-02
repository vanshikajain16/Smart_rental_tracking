"""Stage 1 unit + regression tests.

    pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_loader import load_rentals  # noqa: E402
from src.schema import validate_record  # noqa: E402
from src.stages.stage1 import (  # noqa: E402
    build_asset_record,
    evaluate_cycle,
    evaluate_metrics,
    run_stage1,
)

BASE_ROW = {
    "Equipment ID": "EQX9000",
    "Type": "Grader",  # expected_daily_hours=6, idle_threshold=0.55
    "Customer ID": "CUST01",
    "Site ID": "S001",
    "Expected Return Date": pd.Timestamp("2025-06-01"),
    "Actual Check-In Date": pd.Timestamp("2025-05-30"),
    "Engine Hours/Day": 4.5,
    "Idle Hours/Day": 2.0,
    "Operating Days": 20,
    "Last Operator ID": "OP1",
    "penalty_charged": False,
    "penalty_paid": pd.NA,
    "is_overdue_now": False,
    "cycle_number": 5,
    "is_anomaly_ground_truth": False,
    "idle_ratio": 2.0 / 6.5,
    "still_checked_out": False,
}


def row(**over):
    r = dict(BASE_ROW)
    r.update(over)
    if "Actual Check-In Date" in over and pd.isna(over["Actual Check-In Date"]):
        r["still_checked_out"] = True
    if {"Engine Hours/Day", "Idle Hours/Day"} & over.keys():
        e, i = r["Engine Hours/Day"], r["Idle Hours/Day"]
        r["idle_ratio"] = i / (e + i) if (e + i) else 0.0
    return r


def test_clean_cycle_is_healthy():
    res = evaluate_cycle(row())
    assert res["health_score"] == 100
    assert res["is_anomaly"] is False
    assert res["reasons"] == []


def test_still_checked_out_is_hard_anomaly():
    res = evaluate_cycle(row(Actual_Check_In_Date=None,
                             **{"Actual Check-In Date": None}))
    assert res["is_anomaly"] is True
    assert "still_checked_out" in res["hard_fired"]
    assert res["health_score"] <= 55


def test_overdue_is_hard_anomaly():
    res = evaluate_cycle(row(is_overdue_now=True))
    assert res["is_anomaly"] is True
    assert res["hard_fired"] == ["overdue"]


def test_missing_site_and_operator_flags_both():
    res = evaluate_cycle(row(**{"Site ID": None, "Last Operator ID": None}))
    assert {"no_site", "no_operator"} <= set(res["hard_fired"])
    assert "No site assigned" in res["reasons"]
    assert "No operator assigned" in res["reasons"]
    assert res["is_anomaly"] is True


def test_high_idle_alone_is_not_anomaly_but_dents_health():
    # idle ratio 0.60 > 0.55 threshold, but idle hours 3.0 < 8.5 severe cutoff
    res = evaluate_cycle(row(**{"Engine Hours/Day": 2.0, "Idle Hours/Day": 3.0}))
    assert any("High idle ratio" in r for r in res["reasons"])
    assert res["is_anomaly"] is False
    assert res["health_score"] < 100


def test_high_and_severe_idle_together_is_anomaly():
    res = evaluate_cycle(row(**{"Engine Hours/Day": 1.0, "Idle Hours/Day": 10.0}))
    assert res["is_anomaly"] is True
    assert not res["hard_fired"]  # soft-only path


def test_unpaid_penalty_beats_penalty_charged():
    res = evaluate_cycle(row(penalty_charged=True, penalty_paid=False))
    assert "unpaid_penalty" in res["hard_fired"]
    assert "penalty_charged" not in res["hard_fired"]


def test_idle_ratio_reason_matches_spec_format():
    res = evaluate_cycle(row(**{"Engine Hours/Day": 2.7, "Idle Hours/Day": 7.3}))
    assert any(r.startswith("High idle ratio (") and "threshold)" in r
               for r in res["reasons"])


def test_health_score_clamped_to_zero():
    res = evaluate_cycle(row(**{
        "Actual Check-In Date": None, "Site ID": None, "Last Operator ID": None,
        "is_overdue_now": True, "penalty_charged": True, "penalty_paid": False,
        "Engine Hours/Day": 0.0, "Idle Hours/Day": 12.0,
    }))
    assert res["health_score"] == 0


def test_build_asset_record_schema_and_current_cycle():
    rows = pd.DataFrame([
        row(cycle_number=1, **{"Engine Hours/Day": 4.0, "Idle Hours/Day": 2.0}),
        row(cycle_number=2, **{"Site ID": None, "Last Operator ID": None,
                               "Engine Hours/Day": 1.0, "Idle Hours/Day": 11.0}),
    ])
    rec = build_asset_record(rows)
    validate_record(rec)
    assert rec["equipment_id"] == "EQX9000"
    assert rec["site_id"] is None            # current cycle = highest cycle_number
    assert rec["demand_forecast"] is None
    assert rec["recommendation"] is None
    assert any("No site assigned" in r for r in rec["reasons"])


def test_reallocatable_requires_availability():
    still_out = pd.DataFrame([
        row(cycle_number=3, **{"Actual Check-In Date": None,
                               "is_overdue_now": True,
                               "Engine Hours/Day": 1.0, "Idle Hours/Day": 11.0}),
    ])
    assert build_asset_record(still_out)["reallocatable"] is False

    idle_back = pd.DataFrame([
        row(cycle_number=3, **{"Engine Hours/Day": 1.0, "Idle Hours/Day": 8.0}),
    ])
    assert build_asset_record(idle_back)["reallocatable"] is True


# --------------------------------------------------------------------------- #
# Regression guard on the real dataset
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def real_run():
    df = load_rentals()
    return run_stage1(df)


def test_every_asset_record_conforms(real_run):
    assets, _ = real_run
    assert len(assets) == 82
    for rec in assets:
        validate_record(rec)


def test_metrics_stay_strong(real_run):
    _, rows_df = real_run
    m = evaluate_metrics(rows_df)
    assert m["precision"] >= 0.90
    assert m["recall"] >= 0.85
    assert m["f1"] >= 0.88
