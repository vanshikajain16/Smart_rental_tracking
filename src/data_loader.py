"""Typed loaders for the unified dataset.

Everything downstream reads through here so date parsing, null normalisation and
row ordering are done exactly once and identically for every stage.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import CUSTOMERS_CSV, RENTALS_UNIFIED_CSV

DATE_COLUMNS = [
    "Check-Out Date",
    "Check-In Date",
    "Expected Return Date",
    "Actual Check-In Date",
]
BOOL_COLUMNS = ["penalty_charged", "is_overdue_now", "is_anomaly_ground_truth"]
# Columns where an empty cell is a meaningful "not assigned", kept as None.
NULLABLE_STR_COLUMNS = ["Site ID", "Last Operator ID"]


def _to_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return (
        series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
    )


def _to_nullable_bool(series: pd.Series) -> pd.Series:
    """penalty_paid: True / False / <NA> (only set when a penalty was charged)."""
    out = []
    for v in series:
        if pd.isna(v):
            out.append(pd.NA)
        elif str(v).strip().lower() in ("true", "1", "yes"):
            out.append(True)
        else:
            out.append(False)
    return pd.Series(out, index=series.index, dtype="object")


def load_rentals(path: str | Path = RENTALS_UNIFIED_CSV) -> pd.DataFrame:
    """Load rentals_unified.csv fully typed and sorted by (asset, cycle).

    - date columns -> datetime64 (NaT where still checked out)
    - penalty_charged / is_overdue_now / is_anomaly_ground_truth -> bool
    - penalty_paid -> object column of {True, False, <NA>}
    - Site ID / Last Operator ID -> str or None
    - rows ordered by Equipment ID then cycle_number (asset history order)
    """
    df = pd.read_csv(path)

    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in BOOL_COLUMNS:
        df[col] = _to_bool(df[col])
    df["penalty_paid"] = _to_nullable_bool(df["penalty_paid"])
    for col in NULLABLE_STR_COLUMNS:
        df[col] = df[col].where(df[col].notna(), None)
        df[col] = df[col].map(lambda v: v if v is None else str(v).strip() or None)

    df["cycle_number"] = df["cycle_number"].astype(int)
    df["Operating Days"] = df["Operating Days"].astype(int)

    df = df.sort_values(["Equipment ID", "cycle_number"]).reset_index(drop=True)

    # Convenience derived columns (never model inputs; just save every stage
    # recomputing them). idle_ratio is NaN only if a row logs zero hours total.
    total_hours = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = np.where(total_hours > 0, df["Idle Hours/Day"] / total_hours, 0.0)
    df["still_checked_out"] = df["Actual Check-In Date"].isna()
    return df


def load_customers(path: str | Path = CUSTOMERS_CSV) -> pd.DataFrame:
    """Load customers.csv. Reliability Score / Risk Tier are null until Stage 5."""
    df = pd.read_csv(path)
    df["Customer ID"] = df["Customer ID"].astype(str).str.strip()
    df["Phone Number"] = df["Phone Number"].astype(str).str.strip()
    return df
