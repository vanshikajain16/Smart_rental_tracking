"""Central configuration: filesystem paths, asset-type config loader, and the
Stage 1 rule book (thresholds + health-score weights).

Every tunable number for Stage 1 lives in ``STAGE1_RULES`` so the rule engine
itself stays declarative and the demo can be re-tuned without touching logic.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"

ASSET_TYPE_CONFIG_JSON = DATA_RAW / "asset_type_config.json"
RENTALS_UNIFIED_CSV = DATA_PROCESSED / "rentals_unified.csv"
CUSTOMERS_CSV = DATA_PROCESSED / "customers.csv"

# Stage 1 outputs
STAGE1_ROWS_CSV = DATA_PROCESSED / "stage1_rows.csv"          # per-rental-cycle detail
STAGE1_ASSETS_JSON = DATA_PROCESSED / "stage1_assets.json"    # per-asset unified records

# The dataset covers calendar-year 2025; the latest check-in is 2025-12-31.
# Treat that as "today" for any age/overdue arithmetic on the historical data.
AS_OF_DATE = date(2025, 12, 31)

# --------------------------------------------------------------------------- #
# Asset-type config
# --------------------------------------------------------------------------- #
# Used when a Type is missing from asset_type_config.json.
DEFAULT_TYPE_CONFIG = {
    "expected_daily_hours": 8,
    "idle_threshold": 0.6,
    "custom_fields": [],
}


@lru_cache(maxsize=1)
def load_asset_config(path: str | Path = ASSET_TYPE_CONFIG_JSON) -> dict:
    """Return the per-Type config dict from asset_type_config.json."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def type_config(asset_type: str) -> dict:
    """Config for one asset Type, falling back to DEFAULT_TYPE_CONFIG."""
    return load_asset_config().get(asset_type, DEFAULT_TYPE_CONFIG)


# --------------------------------------------------------------------------- #
# Stage 1 rule book
# --------------------------------------------------------------------------- #
# health_score = clamp(100 - sum(weight of every fired rule), 0, 100)
#
# ``severity`` per rule:
#   "hard" -> on its own it makes the cycle an anomaly (these match the
#             deterministic drivers of is_anomaly_ground_truth: P(anom)=1.0).
#   "soft" -> contributes to the health score; only flags an anomaly when the
#             idle pattern is both proportionally and absolutely extreme
#             (high_idle AND severe_idle together).
STAGE1_RULES = {
    "weights": {
        "still_checked_out": 45,     # Actual Check-In Date is null
        "overdue": 40,               # is_overdue_now
        "no_site": 20,               # Site ID missing
        "no_operator": 20,           # Last Operator ID missing
        "unpaid_penalty": 30,        # penalty_charged and not penalty_paid
        "penalty_charged": 15,       # penalty_charged (paid or unknown)
        "high_idle": 25,             # idle_ratio > type idle_threshold
        "severe_idle": 20,           # Idle Hours/Day > severe_idle_hours
        "low_utilization": 15,       # Engine Hours/Day < low_util_fraction * expected
    },
    # Idle Hours/Day above this absolute value is "severe" regardless of ratio.
    # Tuned against is_anomaly_ground_truth (F1 ~0.93 for hard OR
    # (high_idle AND severe_idle)).
    "severe_idle_hours": 8.5,
    # Engine Hours/Day below this fraction of the type's expected_daily_hours
    # counts as under-utilised.
    "low_util_fraction": 0.5,
    # An asset is reallocatable only if its current-cycle health is at or below
    # this and it is physically available (not still checked out / overdue).
    "reallocatable_health_max": 60,
    # Chronic flag: anomaly in at least this many of the last N completed cycles.
    "chronic_lookback": 3,
    "chronic_min_flags": 2,
}
