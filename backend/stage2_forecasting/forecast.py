"""Stage 2 - demand forecasting: inference.

Public API
----------
    forecast_demand(site_id, type, days_ahead) -> dict

The dict always carries:
    predicted_need_score : int 0-100   (headline "how much will this site want
                                        this equipment type soon")
    reason               : str         (plain-language explanation)

plus supporting fields (method, monthly_rate, trend_per_month, expected_checkouts,
predicted_need_days, confidence) and a ready-to-embed ``demand_forecast`` block
matching the unified per-asset record shape
    {"site_id": ..., "type": ..., "predicted_need_days": ...}

Model source
------------
Reads data/processed/stage2_demand_model.json produced by
train_holt_winters.py. If that file is missing it trains it once, automatically.

Scoring, in brief
-----------------
1. effective monthly checkout rate for the group:
     - holt groups        : 60/40 blend of the damped Holt projection and the
                            last-3-months recency rate, floored at 25% of the
                            historical mean (an active site x type rarely goes
                            to literal zero).
     - freq_recency groups: 50/50 blend of historical and recency rate.
     - unseen site        : per-Type fleet average (type_fallback).
     - unseen Type        : global fleet average (global_fallback).
2. recency decay: scale the rate down if the site has not touched this type in
   > 45 / 75 / 120 days.
3. score = saturating(rate) + trend nudge + horizon nudge, then capped by how
   trustworthy the method is (holt 100, freq_recency 75, type 60, global 40).
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

REPO_ROOT = HERE.parents[1]
MODEL_JSON = REPO_ROOT / "data" / "processed" / "stage2_demand_model.json"

# scoring constants
RATE_HALF_SCORE = 2.5      # monthly rate that maps to ~50/100 before nudges
METHOD_SCORE_CAP = {"holt": 100, "freq_recency": 75,
                    "type_fallback": 60, "global_fallback": 40}
_model_cache: dict | None = None


# --------------------------------------------------------------------------- #
# Model access
# --------------------------------------------------------------------------- #
def _load_model(force_reload: bool = False) -> dict:
    global _model_cache
    if _model_cache is not None and not force_reload:
        return _model_cache
    if not MODEL_JSON.exists():
        import train_holt_winters
        train_holt_winters.main()
    with open(MODEL_JSON, "r", encoding="utf-8") as fh:
        _model_cache = json.load(fh)
    return _model_cache


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _holt_project(state: dict, params: dict, h: int) -> list[float]:
    level, trend, phi = state["level"], state["trend"], params["phi"]
    out = []
    for s in range(1, h + 1):
        damp = sum(phi ** i for i in range(1, s + 1))
        out.append(max(0.0, level + damp * trend))
    return out


def _recency_factor(days_since_last: int) -> tuple[float, str]:
    if days_since_last <= 45:
        return 1.0, ""
    if days_since_last <= 75:
        return 0.85, f"last checkout {days_since_last}d ago (cooling)"
    if days_since_last <= 120:
        return 0.70, f"last checkout {days_since_last}d ago (well cooled)"
    return 0.50, f"last checkout {days_since_last}d ago (dormant)"


def _band(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "elevated"
    if score >= 35:
        return "moderate"
    return "low"


def _trend_word(t: float) -> str:
    if t > 0.15:
        return "rising"
    if t < -0.15:
        return "declining"
    return "roughly flat"


def _a(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class DemandForecast:
    site_id: str
    type: str
    days_ahead: int
    predicted_need_score: int
    predicted_need_days: int
    expected_checkouts: float
    monthly_rate: float
    trend_per_month: float
    method: str
    confidence: str
    reason: str
    demand_forecast: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def forecast_demand(site_id: str, type: str, days_ahead: int) -> dict:
    """Predict near-term demand for ``type`` equipment at ``site_id``.

    Returns a dict (see module docstring). ``days_ahead`` is clamped to 1..365.
    """
    model = _load_model()
    site_id = str(site_id).strip()
    type = str(type).strip()
    days_ahead = int(_clip(int(days_ahead), 1, 365))
    month_days = model["meta"].get("month_days", 30.0)
    h = max(1, math.ceil(days_ahead / month_days))

    key = f"{site_id}|{type}"
    groups = model["groups"]
    trend_pm = 0.0
    resid_std = None
    active_months = None
    days_since_last = 0
    fit_span = model["meta"].get("fit_months", [])

    if key in groups:
        g = groups[key]
        method = g["method"]
        hist_rate = g["hist_monthly_rate"]
        recency_rate = g["recency_monthly_rate"]
        trend_pm = g.get("trend_per_month", 0.0)
        active_months = g.get("nonzero_months")
        days_since_last = g.get("days_since_last_checkout", 0)
        if method == "holt":
            resid_std = g.get("fit", {}).get("resid_std")
            proj = _holt_project(g["state"], g["params"], h)
            holt_rate = sum(proj) / len(proj)
            holt_rate = max(holt_rate, 0.25 * hist_rate)   # zero-collapse floor
            base_rate = 0.6 * holt_rate + 0.4 * recency_rate
        else:  # freq_recency
            base_rate = 0.5 * hist_rate + 0.5 * recency_rate
    elif type in model["type_fallback"]:
        method = "type_fallback"
        tf = model["type_fallback"][type]
        hist_rate, recency_rate = tf["monthly_rate"], tf["recency_monthly_rate"]
        base_rate = 0.5 * hist_rate + 0.5 * recency_rate
    else:
        method = "global_fallback"
        hist_rate = recency_rate = model["global_fallback"]["monthly_rate"]
        base_rate = hist_rate

    decay, decay_note = _recency_factor(days_since_last)
    rate = max(0.0, base_rate * decay)

    expected = rate * days_ahead / month_days
    predicted_need_days = int(_clip(round(month_days / max(rate, 0.05)),
                                    1, days_ahead))

    # ---- score --------------------------------------------------------- #
    score = 100.0 * rate / (rate + RATE_HALF_SCORE)
    if method == "holt":
        score += _clip(15.0 * trend_pm / max(rate, 1.0), -12, 12)
    score += _clip((days_ahead - month_days) / 60.0 * 6.0, -4, 10)
    if resid_std is not None and rate > 0:
        score -= _clip(10.0 * (resid_std / max(rate, 1.0) - 0.5), 0, 10)
    score = int(round(_clip(score, 0, METHOD_SCORE_CAP[method])))

    if method == "holt":
        confidence = ("high" if (resid_std is not None and rate > 0
                                 and resid_std / max(rate, 1.0) < 0.5)
                      else "medium")
    elif method == "freq_recency":
        confidence = "medium"
    else:
        confidence = "low"

    reason = _build_reason(
        site_id, type, days_ahead, method, hist_rate, recency_rate, rate,
        trend_pm, active_months, fit_span, expected, predicted_need_days,
        score, confidence, decay_note,
        n_type_sites=model["type_fallback"].get(type, {}).get("n_groups"),
    )

    result = DemandForecast(
        site_id=site_id, type=type, days_ahead=days_ahead,
        predicted_need_score=score,
        predicted_need_days=predicted_need_days,
        expected_checkouts=round(expected, 2),
        monthly_rate=round(rate, 2),
        trend_per_month=round(trend_pm, 2),
        method=method, confidence=confidence, reason=reason,
        demand_forecast={
            "site_id": site_id, "type": type,
            "predicted_need_days": predicted_need_days,
        },
    )
    return result.as_dict()


def _build_reason(site, typ, days_ahead, method, hist_rate, recency_rate, rate,
                  trend_pm, active_months, fit_span, expected,
                  predicted_need_days, score, confidence, decay_note,
                  n_type_sites=None) -> str:
    span_txt = ""
    if fit_span:
        span_txt = f" ({fit_span[0]}..{fit_span[-1]})"

    if method == "holt":
        lead = (
            f"{site} checked out {_a(typ)} {hist_rate:.1f}x/month across "
            f"{active_months} active months{span_txt}; trend {_trend_word(trend_pm)} "
            f"({trend_pm:+.2f}/mo). Holt-Winters (level+trend, no seasonality) "
            f"blended with recent activity projects ~{rate:.1f}/month"
        )
    elif method == "freq_recency":
        lead = (
            f"{site} has thin {typ} history ({hist_rate:.1f}x/month overall, "
            f"{recency_rate:.1f}x recently) - below the volume bar for a fitted "
            f"trend, so a recency-weighted frequency of ~{rate:.1f}/month is used"
        )
    elif method == "type_fallback":
        lead = (
            f"No checkout history for {_a(typ)} at {site}. Falling back to the "
            f"fleet-wide {typ} average (~{hist_rate:.1f}/month across "
            f"{n_type_sites} sites) -> ~{rate:.1f}/month"
        )
    else:
        lead = (
            f"No history for {typ!r} at {site} and no per-type baseline; using "
            f"the global fleet average of ~{rate:.1f}/month"
        )

    n = round(expected)
    tail = (
        f" -> about {n} {typ} checkout{'' if n == 1 else 's'} expected at {site} "
        f"over the next {days_ahead} days, next need within "
        f"~{predicted_need_days} days. {_band(score).capitalize()} demand "
        f"(score {score}/100, {confidence} confidence)."
    )
    if decay_note:
        tail = f" [{decay_note}]" + tail
    return lead + tail


# --------------------------------------------------------------------------- #
# Smoke test - run:  python backend/stage2_forecasting/forecast.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    _load_model()
    print("=" * 78)
    print("STAGE 2 - forecast_demand() smoke test")
    print("=" * 78)

    cases = [
        # present in the data - different regimes
        ("S004", "Crane", 30),      # highest-volume group
        ("S004", "Crane", 90),      # same group, longer horizon
        ("S005", "Crane", 60),      # rising trend
        ("S003", "Excavator", 30),  # low volume + declining (zero-collapse floor)
        ("S001", "Grader", 45),     # middling
        # fallbacks
        ("S099", "Grader", 30),     # unseen site  -> type_fallback
        ("S001", "Generator", 30),  # unseen type  -> global_fallback
    ]
    for site, typ, days in cases:
        r = forecast_demand(site, typ, days)
        print(f"\n{site} / {typ} / next {days}d")
        print(f"  score={r['predicted_need_score']}/100  "
              f"need_within~{r['predicted_need_days']}d  "
              f"exp_checkouts={r['expected_checkouts']}  "
              f"rate={r['monthly_rate']}/mo  method={r['method']}  "
              f"conf={r['confidence']}")
        print(f"  demand_forecast block: {r['demand_forecast']}")
        print(f"  reason: {r['reason']}")
