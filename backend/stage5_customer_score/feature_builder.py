"""Stage 5 - customer reliability scoring: feature builder.

Reads data/processed/rentals_unified.csv, grouped by Customer ID (~35-69
rentals each). Builds a point-in-time PANEL: one row per (customer, cutoff k),
where cutoff k means "we have seen this customer's first k rentals, in
chronological order".

FEATURES (from rentals 1..k only)
    n_rentals            - k, the volume observed so far
    overdue_freq         - share of rentals 1..k that were overdue
                           (is_overdue_now OR Actual Check-In Date is null)
    penalty_rate         - share of rentals 1..k with penalty_charged
    unpaid_penalty_rate  - among penalty_charged rentals, share with
                           penalty_paid == False  (0 if none charged)
    avg_idle_ratio       - mean idle_ratio over rentals 1..k
    recent_overdue_freq  - overdue share over the last min(5, k) rentals

LABEL (from rentals k+1..k+5 only - a genuine FUTURE outcome, never the same
signal restated; same non-circularity rule as Stage 3)
    label = 1 if any of the customer's NEXT 5 rentals is overdue OR an
            unpaid-penalty rental, else 0.
    label = <NA> when the customer has fewer than 5 rentals after cutoff k -
            those rows are excluded from training but still carry features so
            the dashboard can score them.

``customer_snapshot(panel)`` returns the k == total row for each customer: all
of their history as features, label <NA>. That is the row scored into
customers.csv.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = REPO_ROOT / "data" / "processed" / "rentals_unified.csv"
PANEL_CSV = REPO_ROOT / "data" / "processed" / "stage5_panel.csv"

FUTURE_WINDOW = 5

FEATURE_COLUMNS = [
    "n_rentals",
    "overdue_freq",
    "penalty_rate",
    "unpaid_penalty_rate",
    "avg_idle_ratio",
    "recent_overdue_freq",
]

DATE_COLS = ["Check-Out Date", "Expected Return Date", "Actual Check-In Date"]


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    for c in DATE_COLS:
        if not np.issubdtype(df[c].dtype, np.datetime64):
            df[c] = pd.to_datetime(df[c], errors="coerce")

    total = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = np.where(total > 0, df["Idle Hours/Day"] / total, 0.0)

    df["overdue_event"] = (
        df["is_overdue_now"].astype(str).str.strip().str.lower().isin(["true", "1"])
        | df["Actual Check-In Date"].isna()
    )
    charged = (df["penalty_charged"].astype(str).str.strip().str.lower()
               .isin(["true", "1"]))
    paid_false = df["penalty_paid"].astype(str).str.strip().str.lower().eq("false")
    df["penalty_charged_event"] = charged
    df["unpaid_event"] = charged & paid_false
    df["bad_event"] = df["overdue_event"] | df["unpaid_event"]

    # chronological order within a customer
    df = df.sort_values(
        ["Customer ID", "Check-Out Date", "Actual Check-In Date", "Equipment ID"]
    ).reset_index(drop=True)
    return df


def build_panel(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (customer, cutoff k) for k = 1 .. total."""
    if df is None:
        df = pd.read_csv(INPUT_CSV)
    df = _prepare(df)

    rows: list[dict] = []
    for cust, g in df.groupby("Customer ID", sort=True):
        g = g.reset_index(drop=True)
        n = len(g)
        overdue = g["overdue_event"].to_numpy()
        charged = g["penalty_charged_event"].to_numpy()
        unpaid = g["unpaid_event"].to_numpy()
        idle = g["idle_ratio"].to_numpy()
        bad = g["bad_event"].to_numpy()

        for k in range(1, n + 1):
            past_charged = int(charged[:k].sum())
            has_future = (n - k) >= FUTURE_WINDOW
            label = (int(bad[k:k + FUTURE_WINDOW].any())
                     if has_future else pd.NA)
            rows.append({
                "customer_id": str(cust),
                "cutoff_k": k,
                "n_rentals_total": n,
                "has_future_window": has_future,
                "label": label,
                # features
                "n_rentals": k,
                "overdue_freq": float(overdue[:k].mean()),
                "penalty_rate": float(charged[:k].mean()),
                "unpaid_penalty_rate": (past_charged and
                                        float(unpaid[:k].sum() / past_charged)) or 0.0,
                "avg_idle_ratio": float(idle[:k].mean()),
                "recent_overdue_freq": float(overdue[max(0, k - 5):k].mean()),
            })

    panel = pd.DataFrame(rows)
    panel["label"] = panel["label"].astype("Int64")
    return panel


def customer_snapshot(panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """The k == total row for every customer - full history as features."""
    if panel is None:
        panel = build_panel()
    snap = panel[panel["cutoff_k"] == panel["n_rentals_total"]].copy()
    return snap.sort_values("customer_id").reset_index(drop=True)


def _summary(panel: pd.DataFrame) -> None:
    tr = panel[panel["has_future_window"]]
    print(f"panel rows            : {len(panel)}")
    print(f"customers             : {panel['customer_id'].nunique()}")
    print(f"trainable rows        : {len(tr)}  "
          f"(excluded {len(panel) - len(tr)} without a 5-rental future window)")
    y = tr["label"].astype(int)
    print(f"label = 1 rate        : {y.mean():.3f}  ({int(y.sum())} positive)")
    print(f"majority baseline acc : {max(y.mean(), 1 - y.mean()):.3f}")
    print("\nper-customer trainable positives:")
    print(tr.groupby("customer_id")["label"].agg(["sum", "count"]).to_string())
    print("\nfeature describe (trainable rows):")
    print(tr[FEATURE_COLUMNS].describe().T.round(3))


if __name__ == "__main__":
    panel = build_panel()
    panel.to_csv(PANEL_CSV, index=False)
    print(f"wrote {PANEL_CSV.relative_to(REPO_ROOT)}\n")
    _summary(panel)
