"""Stage 4 - reallocation matching engine + dealer-level renewal-risk signal.

Everything joins on the one shared file: Stage 1 (health + idle/unassigned
flags), Stage 2 (per site x type demand forecast) and Stage 3 (ML
"reallocatable" flag) all key off data/processed/rentals_unified.csv, so we take
each asset's LATEST cycle (max cycle_number) as its current state and join on
(Equipment ID, cycle_number).

Part A - reallocation matches
    A candidate asset is one that is, at its current cycle:
      * flagged idle OR unassigned by Stage 1, AND
      * low health score (<= HEALTH_MAX), AND
      * marked reallocatable by Stage 3.
    Each candidate is matched only against OTHER sites belonging to the SAME
    Customer ID, ranked by Stage 2's demand forecast for the asset's Type. A
    move is proposed only when some other site both clears MIN_DEMAND_SCORE and
    wants the type more than the asset's current site does. Movement never
    crosses Customer IDs.
    Output: a list of objects whose ``recommendation`` value matches the Shared
    Contract's "recommendation" shape exactly:
        {"action", "from_site", "to_site", "reason"}

Part B - dealer aggregate (no movement, just a signal)
    Group every rental cycle by Customer ID, compute average health and a health
    trend (slope of health vs time), and flag customers whose health is
    trending down as ``renewal_risk``.

Run:
    python backend/stage4_matching/reallocation_engine.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (str(REPO_ROOT), str(REPO_ROOT / "backend" / "stage2_forecasting")):
    if p not in sys.path:
        sys.path.insert(0, p)

from forecast import forecast_demand  # noqa: E402  (backend/stage2_forecasting)
from src.data_loader import load_rentals  # noqa: E402
from src.stages.stage1 import evaluate_cycle  # noqa: E402

STAGE1_OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage1_output.csv"
STAGE3_OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage3_output.csv"
CUSTOMERS_CSV = REPO_ROOT / "data" / "processed" / "customers.csv"

RECS_JSON = REPO_ROOT / "data" / "processed" / "stage4_recommendations.json"
RECS_DETAIL_JSON = REPO_ROOT / "data" / "processed" / "stage4_recommendations_detailed.json"
CUST_AGG_JSON = REPO_ROOT / "data" / "processed" / "stage4_customer_aggregate.json"

# ---- tunables ---------------------------------------------------------- #
HEALTH_MAX = 60            # "low health score" cutoff for a candidate
MIN_DEMAND_SCORE = 45      # destination must want the type at least this much
FORECAST_HORIZON_DAYS = 30
MAX_MOVES_PER_DEST_TYPE = 1  # don't dogpile idle units into one site in a pass

TREND_DOWN_SLOPE = -1.0    # health points/month below this => "down"
TREND_UP_SLOPE = 1.0
RENEWAL_RISK_HEALTH = 75   # trending down AND current avg health under this
RENEWAL_RISK_HARD_HEALTH = 45  # any customer this unhealthy is at risk


def _a(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def _as_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


# --------------------------------------------------------------------------- #
# Shared current-state table (also consumed by pipeline.py)
# --------------------------------------------------------------------------- #
def latest_cycle_state() -> pd.DataFrame:
    """One row per physical asset = its latest cycle, with Stage 1/2-ready
    fields plus Stage 1 health + reasons and Stage 3's reallocatable flag."""
    rentals = load_rentals()  # typed; has idle_ratio, still_checked_out

    ev = rentals.apply(lambda r: evaluate_cycle(r.to_dict()), axis=1)
    rentals = rentals.assign(
        health_score=[e["health_score"] for e in ev],
        s1_reasons=[e["reasons"] for e in ev],
        s1_is_anomaly=[e["is_anomaly"] for e in ev],
    )

    s1 = pd.read_csv(STAGE1_OUTPUT_CSV)[
        ["Equipment ID", "cycle_number", "idle_flag", "unassigned_flag",
         "overdue_flag", "is_flagged", "idle_threshold"]
    ]
    for c in ["idle_flag", "unassigned_flag", "overdue_flag", "is_flagged"]:
        s1[c] = _as_bool(s1[c])

    s3 = pd.read_csv(STAGE3_OUTPUT_CSV)[
        ["Equipment ID", "cycle_number", "reallocatable_probability",
         "reallocatable_flag"]
    ]
    s3["reallocatable_flag"] = _as_bool(s3["reallocatable_flag"])

    merged = (rentals
              .merge(s1, on=["Equipment ID", "cycle_number"], how="left")
              .merge(s3, on=["Equipment ID", "cycle_number"], how="left"))

    latest = (merged.sort_values(["Equipment ID", "cycle_number"])
              .groupby("Equipment ID", as_index=False).tail(1)
              .reset_index(drop=True))
    return latest


def _customer_site_map(state: pd.DataFrame) -> dict[str, list[str]]:
    out: dict[str, set] = {}
    for cust, site in zip(state["Customer ID"], state["Site ID"]):
        if pd.notna(site):
            out.setdefault(str(cust), set()).add(str(site))
    return {c: sorted(s) for c, s in out.items()}


# --------------------------------------------------------------------------- #
# Part A - reallocation matches
# --------------------------------------------------------------------------- #
def recommend_reallocations(state: pd.DataFrame | None = None,
                            horizon_days: int = FORECAST_HORIZON_DAYS) -> list[dict]:
    """Return a list of ``{equipment_id, customer_id, type, from_health,
    recommendation}`` where ``recommendation`` matches the Shared Contract shape
    exactly. Only intra-customer moves are ever produced."""
    if state is None:
        state = latest_cycle_state()
    sites_by_customer = _customer_site_map(state)

    is_candidate = (
        (state["idle_flag"].fillna(False) | state["unassigned_flag"].fillna(False))
        & (state["health_score"] <= HEALTH_MAX)
        & (state["reallocatable_flag"].fillna(False))
    )
    candidates = state[is_candidate].sort_values("health_score")

    dest_used: dict[tuple[str, str, str], int] = {}
    results: list[dict] = []

    for _, asset in candidates.iterrows():
        cust = str(asset["Customer ID"])
        typ = str(asset["Type"])
        from_site = asset["Site ID"]
        from_site = None if pd.isna(from_site) else str(from_site)
        eq_id = str(asset["Equipment ID"])
        idle_ratio = float(asset["idle_ratio"])
        health = int(asset["health_score"])

        other_sites = [s for s in sites_by_customer.get(cust, [])
                       if s != from_site]
        if not other_sites:
            continue

        here_score = (forecast_demand(from_site, typ, horizon_days)["predicted_need_score"]
                      if from_site else 0)

        ranked = sorted(
            (forecast_demand(s, typ, horizon_days) for s in other_sites),
            key=lambda f: f["predicted_need_score"], reverse=True,
        )
        chosen = None
        for f in ranked:
            key = (cust, f["site_id"], typ)
            if dest_used.get(key, 0) >= MAX_MOVES_PER_DEST_TYPE:
                continue
            if f["predicted_need_score"] < MIN_DEMAND_SCORE:
                continue
            if f["predicted_need_score"] <= here_score:
                continue
            chosen = f
            dest_used[key] = dest_used.get(key, 0) + 1
            break

        if chosen is None:
            continue

        reason = (
            f"Idle {idle_ratio:.0%} at {from_site} (health {health}/100); "
            f"{chosen['site_id']} forecasted to need {_a(typ)} within "
            f"~{chosen['predicted_need_days']} days "
            f"(demand {chosen['predicted_need_score']}/100 vs {here_score}/100 here)"
        )
        results.append({
            "equipment_id": eq_id,
            "customer_id": cust,
            "type": typ,
            "from_health": health,
            "recommendation": {
                "action": "move",
                "from_site": from_site,
                "to_site": chosen["site_id"],
                "reason": reason,
            },
        })
    return results


# --------------------------------------------------------------------------- #
# Part B - dealer aggregate / renewal risk
# --------------------------------------------------------------------------- #
def _health_all_cycles() -> pd.DataFrame:
    rentals = load_rentals()
    health = rentals.apply(lambda r: evaluate_cycle(r.to_dict())["health_score"],
                           axis=1)
    return rentals.assign(health_score=health)[
        ["Customer ID", "Check-Out Date", "cycle_number", "health_score"]
    ]


def customer_health_aggregate(state: pd.DataFrame | None = None) -> list[dict]:
    if state is None:
        state = latest_cycle_state()

    # dtype=str so "+91..." phone numbers are not parsed as int (drops the '+').
    phones = (pd.read_csv(CUSTOMERS_CSV, dtype=str)
              .set_index("Customer ID")["Phone Number"].to_dict())
    all_cycles = _health_all_cycles()
    t0 = all_cycles["Check-Out Date"].min()

    current_health = (state.groupby("Customer ID")["health_score"]
                      .mean().round(1).to_dict())
    current_counts = state.groupby("Customer ID").size().to_dict()

    out: list[dict] = []
    for cust, grp in all_cycles.groupby("Customer ID"):
        grp = grp.sort_values("Check-Out Date")
        months = (grp["Check-Out Date"] - t0).dt.days / 30.0
        if months.nunique() >= 2:
            slope = float(np.polyfit(months, grp["health_score"], 1)[0])
        else:
            slope = 0.0
        direction = ("down" if slope < TREND_DOWN_SLOPE
                     else "up" if slope > TREND_UP_SLOPE else "flat")
        avg_now = current_health.get(cust, float(grp["health_score"].mean()))
        renewal_risk = bool(
            (direction == "down" and avg_now < RENEWAL_RISK_HEALTH)
            or avg_now < RENEWAL_RISK_HARD_HEALTH
        )
        out.append({
            "customer_id": str(cust),
            "phone_number": phones.get(cust),
            "n_current_assets": int(current_counts.get(cust, 0)),
            "n_cycles_observed": int(len(grp)),
            "avg_health_score": round(float(avg_now), 1),
            "avg_health_all_cycles": round(float(grp["health_score"].mean()), 1),
            "health_trend_slope_per_month": round(slope, 2),
            "trend_direction": direction,
            "renewal_risk": renewal_risk,
        })
    out.sort(key=lambda r: (not r["renewal_risk"], r["avg_health_score"]))
    return out


# --------------------------------------------------------------------------- #
def main() -> None:
    state = latest_cycle_state()

    recs = recommend_reallocations(state)
    agg = customer_health_aggregate(state)

    RECS_JSON.write_text(json.dumps([r["recommendation"] for r in recs], indent=2))
    RECS_DETAIL_JSON.write_text(json.dumps(recs, indent=2))
    CUST_AGG_JSON.write_text(json.dumps(agg, indent=2))

    n_cand = int((
        (state["idle_flag"].fillna(False) | state["unassigned_flag"].fillna(False))
        & (state["health_score"] <= HEALTH_MAX)
        & (state["reallocatable_flag"].fillna(False))
    ).sum())

    print("=" * 78)
    print("STAGE 4 - reallocation matching")
    print("=" * 78)
    print(f"assets (latest cycle) : {len(state)}")
    print(f"candidates (idle/unassigned & health<={HEALTH_MAX} & S3 reallocatable)"
          f" : {n_cand}")
    print(f"moves recommended     : {len(recs)}  (intra-customer only)\n")
    for r in recs:
        rc = r["recommendation"]
        print(f"  {r['equipment_id']}  {r['customer_id']}  {r['type']:<10} "
              f"{rc['from_site']} -> {rc['to_site']}")
        print(f"      {rc['reason']}")
    if not recs:
        print("  (no move cleared MIN_DEMAND_SCORE / 'wanted more elsewhere')")

    print("\n" + "=" * 78)
    print("STAGE 4 - dealer aggregate / renewal risk")
    print("=" * 78)
    print(f"  {'customer':<9} {'assets':>6} {'avg_health':>10} {'slope/mo':>9} "
          f"{'trend':>6}  renewal_risk")
    for a in agg:
        print(f"  {a['customer_id']:<9} {a['n_current_assets']:>6} "
              f"{a['avg_health_score']:>10.1f} "
              f"{a['health_trend_slope_per_month']:>9.2f} "
              f"{a['trend_direction']:>6}  {'YES' if a['renewal_risk'] else '-'}")
    n_risk = sum(a["renewal_risk"] for a in agg)
    print(f"\n  renewal_risk customers: {n_risk}/{len(agg)}")

    print(f"\nwrote {RECS_JSON.relative_to(REPO_ROOT)} "
          f"({len(recs)} recommendation objects, exact contract shape)")
    print(f"wrote {RECS_DETAIL_JSON.relative_to(REPO_ROOT)}")
    print(f"wrote {CUST_AGG_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
