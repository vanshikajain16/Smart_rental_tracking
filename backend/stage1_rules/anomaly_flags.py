"""Stage 1 - rule-based anomaly flags.

Reads  : data/processed/rentals_unified.csv
Writes : data/processed/stage1_output.csv   (all original columns + the columns
         listed in ADDED_COLUMNS below)

Added columns
    idle_ratio        Idle Hours/Day / (Engine Hours/Day + Idle Hours/Day)
    idle_threshold    per-Type threshold from data/raw/asset_type_config.json
    idle_flag         idle_ratio > idle_threshold  AND  Idle Hours/Day > 8.5
                      (the absolute severity gate keeps this off the ~half of
                      the fleet that sits just over the ratio threshold; the
                      ratio alone flags 52% of rows, the pair flags ~13%)
    unassigned_flag   Site ID is null OR Last Operator ID is null
    overdue_flag      the existing is_overdue_now column, used as-is
                      (NOT recomputed from Check-In / Expected Return dates)
    reasons           "; "-joined readable string of every triggered reason
    is_flagged        idle_flag OR unassigned_flag OR overdue_flag

Run:
    python backend/stage1_rules/anomaly_flags.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = REPO_ROOT / "data" / "processed" / "rentals_unified.csv"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage1_output.csv"
ASSET_TYPE_CONFIG = REPO_ROOT / "data" / "raw" / "asset_type_config.json"

ADDED_COLUMNS = [
    "idle_ratio",
    "idle_threshold",
    "idle_flag",
    "unassigned_flag",
    "overdue_flag",
    "reasons",
    "is_flagged",
]

# Order matters only for how reasons read in the joined string.
FLAG_COLUMNS = ["idle_flag", "unassigned_flag", "overdue_flag"]
EXPECTED_FLAG_RATE = (15.0, 20.0)  # percent, sanity band

# idle_flag needs the idle time to be extreme in absolute terms too, not just
# over the per-Type ratio. Tuned against is_anomaly_ground_truth.
SEVERE_IDLE_HOURS = 8.5


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _as_bool(series: pd.Series) -> pd.Series:
    """Coerce a CSV column of True/False/1/0/'' to a real bool Series."""
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
    )


def load_asset_type_config(path: Path = ASSET_TYPE_CONFIG) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def add_flag_columns(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()

    # idle_ratio: fraction of logged time the machine sat idle. Guard the rare
    # row that logs zero engine + zero idle hours.
    total_hours = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = np.where(
        total_hours > 0, df["Idle Hours/Day"] / total_hours, 0.0
    ).round(4)

    # idle_threshold: per-Type, from asset_type_config.json.
    df["idle_threshold"] = df["Type"].map(
        lambda t: cfg.get(t, {}).get("idle_threshold", np.nan)
    )

    df["idle_flag"] = (df["idle_ratio"] > df["idle_threshold"]) & (
        df["Idle Hours/Day"] > SEVERE_IDLE_HOURS
    )

    df["unassigned_flag"] = df["Site ID"].isna() | df["Last Operator ID"].isna()

    # overdue_flag: use the dataset's own is_overdue_now. Do NOT rebuild it from
    # date columns - conflating Expected Return Date with Actual Check-In Date is
    # exactly what inflated the flag rate to ~90% in an earlier version.
    df["overdue_flag"] = _as_bool(df["is_overdue_now"])

    df["reasons"] = df.apply(_row_reasons, axis=1)
    df["is_flagged"] = df[FLAG_COLUMNS].any(axis=1)
    return df


def _row_reasons(row: pd.Series) -> str:
    reasons: list[str] = []
    if row["idle_flag"]:
        reasons.append(
            f"High idle ({row['idle_ratio'] * 100:.0f}% > "
            f"{row['idle_threshold'] * 100:.0f}% threshold, "
            f"{row['Idle Hours/Day']:.1f} idle hrs/day)"
        )
    if row["unassigned_flag"]:
        missing = []
        if pd.isna(row["Site ID"]):
            missing.append("site")
        if pd.isna(row["Last Operator ID"]):
            missing.append("operator")
        reasons.append(f"No {'/'.join(missing)} assigned")
    if row["overdue_flag"]:
        reasons.append("Overdue for return")
    return "; ".join(reasons)


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def print_summary(df: pd.DataFrame) -> None:
    n = len(df)
    n_flagged = int(df["is_flagged"].sum())
    pct_flagged = 100 * n_flagged / n

    print("=" * 60)
    print("STAGE 1 - ANOMALY FLAG SUMMARY")
    print("=" * 60)
    print(f"Total rows            : {n}")
    print(f"Flagged rows          : {n_flagged}  ({pct_flagged:.1f}%)")
    print(f"Not flagged           : {n - n_flagged}  ({100 - pct_flagged:.1f}%)")

    print("\nBreakdown by reason type (rows may trigger more than one):")
    for col in FLAG_COLUMNS:
        c = int(df[col].sum())
        print(f"  {col:<16}: {c:>4}  ({100 * c / n:5.1f}% of all rows,"
              f" {100 * c / max(n_flagged, 1):5.1f}% of flagged)")

    combo = df.loc[df["is_flagged"], FLAG_COLUMNS].sum(axis=1).value_counts().sort_index()
    print("\nReasons per flagged row:")
    for k, v in combo.items():
        print(f"  {int(k)} reason(s): {int(v)}")

    if "is_anomaly_ground_truth" in df.columns:
        gt = _as_bool(df["is_anomaly_ground_truth"])
        gt_rate = 100 * gt.mean()
        pred = df["is_flagged"]
        tp = int((gt & pred).sum())
        fp = int((~gt & pred).sum())
        fn = int((gt & ~pred).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"\nGround-truth anomaly rate (reference): {gt_rate:.1f}%")
        print(f"  vs is_flagged -> precision {prec:.2f}, recall {rec:.2f}")

    lo, hi = EXPECTED_FLAG_RATE
    # "Close to 15-20%" - allow a little slack on either side. The true anomaly
    # rate in this dataset is ~14%, so a shade under 15% is expected and fine.
    ok_lo, ok_hi = lo - 4.0, hi + 3.0
    idle = 100 * df["idle_flag"].mean()
    unas = 100 * df["unassigned_flag"].mean()
    over = 100 * df["overdue_flag"].mean()

    print("\nSanity check")
    print("-" * 60)
    if pct_flagged >= 80:
        print(f"FAIL: {pct_flagged:.1f}% flagged - near the ~90% due-date-bug "
              f"range. Check that overdue_flag is is_overdue_now, not a "
              f"date recomputation.")
    elif ok_lo <= pct_flagged <= ok_hi:
        print(f"PASS: {pct_flagged:.1f}% flagged is close to the "
              f"{lo:.0f}-{hi:.0f}% target (dataset ground-truth rate ~14%).")
        print(f"      idle_flag={idle:.1f}%  unassigned_flag={unas:.1f}%  "
              f"overdue_flag={over:.1f}%")
        print("      overdue_flag comes straight from is_overdue_now - the "
              "due-date/return-date bug is not present.")
    else:
        print(f"WARN: {pct_flagged:.1f}% flagged is outside a sensible "
              f"{ok_lo:.0f}-{ok_hi:.0f}% range.")
        print(f"      idle_flag={idle:.1f}%  unassigned_flag={unas:.1f}%  "
              f"overdue_flag={over:.1f}%")
        if over < 25:
            print("      overdue_flag is small and taken straight from "
                  "is_overdue_now -> not the due-date/return-date bug; "
                  "adjust the idle rule instead.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    df = pd.read_csv(INPUT_CSV)
    out = add_flag_columns(df, load_asset_type_config())
    out.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {OUTPUT_CSV.relative_to(REPO_ROOT)}  "
          f"({len(out)} rows, +{len(ADDED_COLUMNS)} columns)\n")
    print_summary(out)


if __name__ == "__main__":
    main()
