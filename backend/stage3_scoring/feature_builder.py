"""Stage 3 - underutilization / "truly reallocatable" scoring: feature builder.

Reads data/processed/rentals_unified.csv. That file already carries real
per-asset rental history (~10 cycles per physical Equipment ID), so no extra
dataset is needed - we just group by Equipment ID and walk the cycles in order.

POINT-IN-TIME RULE
------------------
Every feature for a row uses ONLY information knowable when that rental cycle
ends - i.e. the current cycle's own usage plus *strictly prior* cycles of the
same asset. Rolling stats are built with ``.shift(1)`` before ``.expanding()`` so
the current row never sees itself or any future row. This is the guard against
the leakage bug a previous version had (features that were really the label in
disguise).

LABEL
-----
label = 1  ("truly reallocatable")  if gap_days_to_next_checkout >= 14
label = 0  ("temporarily quiet")    otherwise

Each asset's LAST cycle (max cycle_number) has no known future, so its label is
undefined - those rows get label = <NA> and ``is_last_cycle = True`` and must be
dropped from training (they are still scored at inference).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = REPO_ROOT / "data" / "processed" / "rentals_unified.csv"
ASSET_TYPE_CONFIG = REPO_ROOT / "data" / "raw" / "asset_type_config.json"
FEATURES_CSV = REPO_ROOT / "data" / "processed" / "stage3_features.csv"

LABEL_THRESHOLD_DAYS = 14
DEFAULT_EXPECTED_DAILY_HOURS = 8.0

# Canonical feature set - imported by train_classifier.py and the scorer so the
# column order can never drift between fit and predict.
FEATURE_COLUMNS = [
    "idle_ratio",              # current cycle
    "utilization",             # current cycle: engine hrs / expected daily hrs
    "rental_length_days",      # current cycle
    "cycle_number",            # experience/age of the rental relationship
    "n_prior_cycles",          # how much history backs the prior_* features
    "prior_idle_ratio_mean",   # mean over strictly prior cycles
    "prior_utilization_mean",  # mean over strictly prior cycles
    "prior_idle_ratio_last",   # immediately preceding cycle only (lag 1)
    "prior_rental_length_mean",  # mean over strictly prior cycles
]

DATE_COLS = ["Check-Out Date", "Expected Return Date", "Actual Check-In Date"]


def load_expected_hours(path: Path = ASSET_TYPE_CONFIG) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return {t: c.get("expected_daily_hours", DEFAULT_EXPECTED_DAILY_HOURS)
            for t, c in cfg.items()}


def build_features(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return one row per rental cycle with FEATURE_COLUMNS + bookkeeping cols
    (Equipment ID, Type, cycle_number, gap_days_to_next_checkout, is_last_cycle,
    label).  ``label`` is pandas <NA> for each asset's last cycle.
    """
    if df is None:
        df = pd.read_csv(INPUT_CSV)
    for c in DATE_COLS:
        if not np.issubdtype(df[c].dtype, np.datetime64):
            df[c] = pd.to_datetime(df[c], errors="coerce")

    df = (df.sort_values(["Equipment ID", "cycle_number"])
            .reset_index(drop=True).copy())

    # ---- current-cycle quantities ------------------------------------- #
    total_hours = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = np.where(total_hours > 0,
                                df["Idle Hours/Day"] / total_hours, 0.0)

    exp_hours = load_expected_hours()
    df["_expected_daily_hours"] = (
        df["Type"].map(exp_hours).fillna(DEFAULT_EXPECTED_DAILY_HOURS)
    )
    df["utilization"] = df["Engine Hours/Day"] / df["_expected_daily_hours"]

    # rental length: actual return if known, else the expected return date.
    end_date = df["Actual Check-In Date"].fillna(df["Expected Return Date"])
    df["rental_length_days"] = (end_date - df["Check-Out Date"]).dt.days

    # ---- strictly-prior rolling features (shift(1) then expand) ------- #
    grp = df.groupby("Equipment ID", sort=False)
    df["n_prior_cycles"] = grp.cumcount()
    df["prior_idle_ratio_mean"] = grp["idle_ratio"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["prior_utilization_mean"] = grp["utilization"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["prior_idle_ratio_last"] = grp["idle_ratio"].shift(1)
    df["prior_rental_length_mean"] = grp["rental_length_days"].transform(
        lambda s: s.shift(1).expanding().mean())

    # ---- label + last-cycle flag ------------------------------------- #
    max_cycle = grp["cycle_number"].transform("max")
    df["is_last_cycle"] = df["cycle_number"].eq(max_cycle)
    label = (df["gap_days_to_next_checkout"] >= LABEL_THRESHOLD_DAYS).astype("Int64")
    df["label"] = label.mask(df["is_last_cycle"], other=pd.NA)

    bookkeeping = ["Equipment ID", "Type", "cycle_number",
                   "gap_days_to_next_checkout", "is_last_cycle", "label"]
    keep = bookkeeping + [c for c in FEATURE_COLUMNS if c not in bookkeeping]
    return df[keep].copy()


def _summary(feats: pd.DataFrame) -> None:
    trainable = feats[~feats["is_last_cycle"]]
    print(f"rows total            : {len(feats)}")
    print(f"assets                : {feats['Equipment ID'].nunique()}")
    print(f"last-cycle rows (drop): {int(feats['is_last_cycle'].sum())}")
    print(f"trainable rows        : {len(trainable)}")
    y = trainable["label"].astype(int)
    print(f"label = 1 rate        : {y.mean():.3f}  "
          f"({int(y.sum())} reallocatable / {int((~y.astype(bool)).sum())} quiet)")
    print(f"NaN in prior_* (1st cycles): "
          f"{int(feats['prior_idle_ratio_mean'].isna().sum())} rows "
          f"(imputed in the training pipeline)")
    print("\nfeature describe (trainable rows):")
    with pd.option_context("display.width", 120):
        print(trainable[FEATURE_COLUMNS].describe().T.round(3))


if __name__ == "__main__":
    feats = build_features()
    feats.to_csv(FEATURES_CSV, index=False)
    print(f"wrote {FEATURES_CSV.relative_to(REPO_ROOT)}\n")
    _summary(feats)
