"""Stage 2 - demand forecasting: model training.

Reads  : data/processed/stage1_output.csv
Writes : data/processed/stage2_demand_model.json

What it does
------------
Builds a per-(Site ID, Type) monthly demand signal from historical
``Check-Out Date`` counts, then fits one of two models per group:

1. "holt"  - Holt's linear-trend exponential smoothing (level + damped trend).
             This is the Holt-Winters family with the *seasonal* term switched
             OFF on purpose: the dataset spans a single year (2025-01 -> 2025-12),
             i.e. 12 monthly points. Seasonal Holt-Winters needs at least two
             full seasonal cycles (>= 24 monthly points for a yearly season),
             so a seasonal fit here would be pure overfitting. Level + trend is
             the most structure 12 points can support.

2. "freq_recency" - a plain frequency / recency score, no fitted trend. Used
             when a group is too thin even for a trend fit (see VOLUME_BAR).
             With the current synthetic dataset *every* observed site x type pair
             clears the bar (24-56 checkouts over 9-12 active months), so nothing
             lands here at training time - but the path is exercised at
             inference for sparse / unseen groups (see the demo in forecast.py),
             and each group's chosen rule + reason is printed below.

Synthetic-data corrections
--------------------------
Two months are excluded from the *fit* (kept in the stored history for
transparency):

  * Leading ramp-up month (2025-01): the whole fleet enters service on Jan 1,
    so January has ~118 checkouts vs ~64/month for the rest of the year. Left
    in, it drags every trend strongly negative.
  * Partial trailing month (2025-12): the export stops on the 20th, so December
    is an incomplete count and misleadingly low.

Feb-Nov is essentially stationary (~64/month, mild noise), so after trimming,
most groups fit a near-zero trend and forecast ~= their stable-period mean.
That is the honest read of this data.

A per-Type fallback and a global fallback are also stored, for site x type
combinations that never appear in the history.

Run
---
    python backend/stage2_forecasting/train_holt_winters.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = REPO_ROOT / "data" / "processed" / "stage1_output.csv"
MODEL_JSON = REPO_ROOT / "data" / "processed" / "stage2_demand_model.json"

MONTH_DAYS = 30.0  # treat a "month" as 30 days for all day<->month conversions

# A group needs at least this much history (within the trimmed fit window) to
# get a fitted trend model rather than the frequency/recency fallback.
#   min_checkouts      : below ~15 events monthly counts are mostly 0/1 - a
#                        trend estimate would be noise.
#   min_nonzero_months : need signal in a majority of the fit window.
#   min_span_months    : activity must be spread out, not a single burst.
VOLUME_BAR = {
    "min_checkouts": 15,
    "min_nonzero_months": 6,
    "min_span_months": 8,
}

# Grid for the Holt fit. Deliberately coarse - 10-12 points do not justify more.
ALPHA_GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8]
BETA_GRID = [0.02, 0.05, 0.1, 0.2, 0.3]
PHI_GRID = [0.80, 0.85, 0.90, 0.95, 1.0]  # 1.0 == undamped

# Trim rules for the synthetic-data artifacts described in the module docstring.
RAMP_RATIO = 1.5           # month0 total > RAMP_RATIO * median(rest) -> drop it
PARTIAL_TAIL_DAY = 25      # last calendar day < this -> last month is partial


# --------------------------------------------------------------------------- #
# Monthly demand signal
# --------------------------------------------------------------------------- #
def build_monthly_matrix(df: pd.DataFrame):
    """Return (month_index, {(site,type): counts}, fit_start, fit_end).

    fit_start/fit_end (end exclusive) bound the window used for fitting, after
    dropping the leading ramp-up month and any partial trailing month.
    """
    co = pd.to_datetime(df["Check-Out Date"])
    start = co.min().to_period("M").to_timestamp()
    end = co.max().to_period("M").to_timestamp()
    month_index = pd.date_range(start, end, freq="MS")
    n_months = len(month_index)

    work = df.assign(_co=co).dropna(subset=["Site ID", "Type"])
    groups: dict[tuple[str, str], np.ndarray] = {}
    for (site, typ), sub in work.groupby(["Site ID", "Type"]):
        groups[(site, typ)] = (
            sub.set_index("_co").resample("MS").size()
            .reindex(month_index, fill_value=0).to_numpy(dtype=float)
        )

    fleet_totals = np.sum(list(groups.values()), axis=0)

    # partial trailing month?
    fit_end = n_months
    if co.max().day < PARTIAL_TAIL_DAY:
        fit_end = n_months - 1

    # leading ramp-up month?
    fit_start = 0
    rest_median = float(np.median(fleet_totals[1:fit_end])) if fit_end > 1 else 0.0
    if rest_median > 0 and fleet_totals[0] > RAMP_RATIO * rest_median:
        fit_start = 1

    if fit_end - fit_start < VOLUME_BAR["min_span_months"]:
        # never trim below a usable window
        fit_start, fit_end = 0, n_months

    return month_index, groups, fit_start, fit_end, fleet_totals


# --------------------------------------------------------------------------- #
# Holt's linear trend (damped) - hand-rolled, no statsmodels dependency
# --------------------------------------------------------------------------- #
def _holt_pass(y: np.ndarray, alpha: float, beta: float, phi: float):
    """One forward pass. Returns (fitted one-step-ahead, level, trend, sse)."""
    n = len(y)
    level = float(y[0])
    trend = float(np.mean(np.diff(y[: min(4, n)]))) if n > 1 else 0.0
    fitted = np.empty(n)
    fitted[0] = level
    sse = 0.0
    for t in range(1, n):
        prev_level = level
        forecast = level + phi * trend
        fitted[t] = forecast
        err = y[t] - forecast
        sse += err * err
        level = alpha * y[t] + (1 - alpha) * forecast
        trend = beta * (level - prev_level) + (1 - beta) * phi * trend
    return fitted, level, trend, sse


def fit_holt(y: np.ndarray) -> dict:
    """Grid-search alpha/beta/phi minimising one-step-ahead SSE."""
    best = None
    for alpha, beta, phi in product(ALPHA_GRID, BETA_GRID, PHI_GRID):
        fitted, level, trend, sse = _holt_pass(y, alpha, beta, phi)
        if best is None or sse < best["sse"]:
            resid = y[1:] - fitted[1:]
            best = {
                "alpha": alpha, "beta": beta, "phi": phi,
                "level": float(level), "trend": float(trend),
                "sse": float(sse),
                "rmse": float(np.sqrt(sse / max(len(y) - 1, 1))),
                "resid_std": float(np.std(resid)) if len(resid) else 0.0,
            }
    return best


def holt_forecast(level: float, trend: float, phi: float, h: int) -> list[float]:
    """h-step damped-trend forecast, clipped at 0 (counts can't be negative)."""
    out = []
    for s in range(1, h + 1):
        damp = sum(phi ** i for i in range(1, s + 1))
        out.append(max(0.0, level + damp * trend))
    return out


# --------------------------------------------------------------------------- #
# Per-group stats (shared by both methods; also feed the reasons in forecast.py)
# --------------------------------------------------------------------------- #
def group_stats(full_counts: np.ndarray, fit_counts: np.ndarray,
                last_checkout: pd.Timestamp, as_of: pd.Timestamp) -> dict:
    nz = fit_counts > 0
    nonzero_months = int(nz.sum())
    if nonzero_months:
        first = int(np.argmax(nz))
        last = int(len(fit_counts) - 1 - np.argmax(nz[::-1]))
        span = last - first + 1
    else:
        span = 0
    recent3 = fit_counts[-3:]
    return {
        "n_checkouts": int(fit_counts.sum()),
        "n_checkouts_all_months": int(full_counts.sum()),
        "nonzero_months": nonzero_months,
        "span_months": int(span),
        "hist_monthly_rate": round(float(fit_counts.mean()), 3),
        "recency_monthly_rate": round(float(recent3.mean()), 3),
        "recent_3_months": recent3.astype(int).tolist(),
        "monthly_counts": full_counts.astype(int).tolist(),
        "fit_monthly_counts": fit_counts.astype(int).tolist(),
        "days_since_last_checkout": int((as_of - last_checkout).days),
    }


def passes_volume_bar(stats: dict) -> bool:
    return (
        stats["n_checkouts"] >= VOLUME_BAR["min_checkouts"]
        and stats["nonzero_months"] >= VOLUME_BAR["min_nonzero_months"]
        and stats["span_months"] >= VOLUME_BAR["min_span_months"]
    )


# --------------------------------------------------------------------------- #
# Train
# --------------------------------------------------------------------------- #
def train(df: pd.DataFrame) -> dict:
    (month_index, matrix, fit_start, fit_end,
     fleet_totals) = build_monthly_matrix(df)
    as_of = pd.to_datetime(df["Check-Out Date"]).max()
    fit_months = [d.strftime("%Y-%m") for d in month_index[fit_start:fit_end]]

    last_checkout = (
        df.assign(_co=pd.to_datetime(df["Check-Out Date"]))
        .dropna(subset=["Site ID", "Type"])
        .groupby(["Site ID", "Type"])["_co"].max()
    )

    groups_out: dict[str, dict] = {}
    method_log: list[tuple] = []
    for (site, typ), full_counts in sorted(matrix.items()):
        fit_counts = full_counts[fit_start:fit_end]
        stats = group_stats(full_counts, fit_counts,
                            last_checkout[(site, typ)], as_of)
        key = f"{site}|{typ}"

        if passes_volume_bar(stats):
            fit = fit_holt(fit_counts)
            trend_pm = fit["trend"] * fit["phi"]
            entry = {
                "method": "holt",
                **stats,
                "params": {"alpha": fit["alpha"], "beta": fit["beta"],
                           "phi": fit["phi"]},
                "state": {"level": round(fit["level"], 4),
                          "trend": round(fit["trend"], 4)},
                "fit": {"rmse": round(fit["rmse"], 3),
                        "resid_std": round(fit["resid_std"], 3)},
                "trend_per_month": round(trend_pm, 3),
                "forecast_next_3_months": [
                    round(x, 2) for x in
                    holt_forecast(fit["level"], fit["trend"], fit["phi"], 3)
                ],
                "method_reason": (
                    f"{stats['n_checkouts']} checkouts over "
                    f"{stats['nonzero_months']}/{len(fit_counts)} active fit "
                    f"months (span {stats['span_months']}) -> above volume bar, "
                    f"Holt level+trend fitted; seasonal term off "
                    f"({len(fit_counts)} monthly points < 24 for a yearly "
                    f"season)."
                ),
            }
        else:
            entry = {
                "method": "freq_recency",
                **stats,
                "trend_per_month": 0.0,
                "method_reason": (
                    f"only {stats['n_checkouts']} checkouts / "
                    f"{stats['nonzero_months']} active months / span "
                    f"{stats['span_months']} - below volume bar {VOLUME_BAR}; "
                    f"recency-weighted frequency instead of a fitted trend."
                ),
            }

        groups_out[key] = entry
        method_log.append((key, entry["method"], stats["n_checkouts"],
                           stats["nonzero_months"], stats["span_months"]))

    # Per-Type fallback: mean of per-site rates for that Type.
    type_fallback: dict[str, dict] = {}
    for typ in sorted({t for _, t in matrix}):
        sel = [g for k, g in groups_out.items() if k.endswith(f"|{typ}")]
        type_fallback[typ] = {
            "monthly_rate": round(float(np.mean([g["hist_monthly_rate"] for g in sel])), 3),
            "recency_monthly_rate": round(float(np.mean([g["recency_monthly_rate"] for g in sel])), 3),
            "n_groups": len(sel),
        }
    global_rate = float(np.mean([g["hist_monthly_rate"] for g in groups_out.values()]))

    model = {
        "meta": {
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(INPUT_CSV.relative_to(REPO_ROOT)),
            "n_rows": int(len(df)),
            "date_min": str(pd.to_datetime(df["Check-Out Date"]).min().date()),
            "date_max": str(pd.to_datetime(df["Check-Out Date"]).max().date()),
            "as_of": str(as_of.date()),
            "month_index": [d.strftime("%Y-%m") for d in month_index],
            "fit_months": fit_months,
            "trimmed_leading_ramp": fit_start == 1,
            "trimmed_partial_tail": fit_end == len(month_index) - 1,
            "month_days": MONTH_DAYS,
            "volume_bar": VOLUME_BAR,
            "holt_note": (
                "Holt-Winters, seasonal=None (Holt's linear damped trend). "
                "Single-year history -> 12 monthly points -> seasonal fit "
                "infeasible; leading ramp-up + partial trailing month trimmed "
                "from the fit."
            ),
            "blend_note": (
                "forecast.py blends the Holt projection 60/40 with the "
                "last-3-months recency rate to stay robust on 10-point fits."
            ),
        },
        "groups": groups_out,
        "type_fallback": type_fallback,
        "global_fallback": {"monthly_rate": round(global_rate, 3)},
    }
    model["_method_log"] = method_log
    model["_fleet_totals"] = fleet_totals.astype(int).tolist()
    model["_fit_bounds"] = (fit_start, fit_end)
    return model


def print_report(model: dict) -> None:
    log = model["_method_log"]
    n_holt = sum(1 for r in log if r[1] == "holt")
    n_freq = sum(1 for r in log if r[1] == "freq_recency")
    m = model["meta"]
    fs, fe = model["_fit_bounds"]
    print("=" * 78)
    print("STAGE 2 - DEMAND MODEL TRAINING")
    print("=" * 78)
    print(f"history        : {m['date_min']} -> {m['date_max']}  "
          f"({len(m['month_index'])} monthly points, {m['n_rows']} rows)")
    print(f"fleet totals/mo: {model['_fleet_totals']}")
    print(f"fit window     : {m['fit_months'][0]}..{m['fit_months'][-1]}  "
          f"(months[{fs}:{fe}])  "
          f"trimmed leading ramp={m['trimmed_leading_ramp']}, "
          f"partial tail={m['trimmed_partial_tail']}")
    print(f"groups         : {len(log)} site x type   |   holt: {n_holt}   "
          f"freq_recency: {n_freq}")
    if n_freq == 0:
        print("                 (no observed group hit the fallback; forecast.py "
              "demo shows it on an unseen combo)")
    print(f"volume bar     : {m['volume_bar']}")
    print("\nper-group method (why):")
    print(f"  {'site|type':<16} {'method':<12} {'n':>4} {'act':>4} {'span':>5} "
          f"{'rate/mo':>8} {'trend/mo':>9}  next-3mo")
    for key, method, n, nz, span in log:
        g = model["groups"][key]
        nxt = g.get("forecast_next_3_months", "-")
        print(f"  {key:<16} {method:<12} {n:>4} {nz:>4} {span:>5} "
              f"{g['hist_monthly_rate']:>8.2f} {g['trend_per_month']:>9.2f}  {nxt}")
    print("\ntype fallback (unseen site x type):")
    for t, f in model["type_fallback"].items():
        print(f"  {t:<10} rate/mo={f['monthly_rate']:.2f}  "
              f"recency={f['recency_monthly_rate']:.2f}  ({f['n_groups']} sites)")
    print(f"global fallback rate/mo = {model['global_fallback']['monthly_rate']:.2f}")


def save_model(model: dict, path: Path = MODEL_JSON) -> None:
    out = {k: v for k, v in model.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)


def main() -> None:
    df = pd.read_csv(INPUT_CSV)
    model = train(df)
    save_model(model)
    print_report(model)
    print(f"\nwrote {MODEL_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
