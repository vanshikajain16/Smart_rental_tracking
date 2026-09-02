"""The one canonical per-asset record shape shared by every stage after Stage 1.

Field names are frozen by the project spec. A stage that does not populate a
field yet MUST leave it as ``None`` (or ``[]`` for ``reasons``) rather than
dropping the key.
"""
from __future__ import annotations

# Ordered for stable JSON output.
RECORD_KEYS = (
    "equipment_id",
    "type",
    "customer_id",
    "site_id",
    "health_score",
    "reasons",
    "reallocatable",
    "demand_forecast",
    "recommendation",
)


def new_asset_record(
    equipment_id: str,
    asset_type: str,
    customer_id: str | None,
    site_id: str | None,
    *,
    health_score: int | None = None,
    reasons: list[str] | None = None,
    reallocatable: bool | None = None,
    demand_forecast: dict | None = None,
    recommendation: dict | None = None,
) -> dict:
    """Build a spec-conformant per-asset record.

    Stage 1 fills equipment_id/type/customer_id/site_id/health_score/reasons/
    reallocatable. demand_forecast (Stage 2/4) and recommendation (Stage 4) stay
    ``None`` here.
    """
    return {
        "equipment_id": equipment_id,
        "type": asset_type,
        "customer_id": customer_id,
        "site_id": site_id,
        "health_score": health_score,
        "reasons": list(reasons) if reasons else [],
        "reallocatable": reallocatable,
        "demand_forecast": demand_forecast,
        "recommendation": recommendation,
    }


def validate_record(rec: dict) -> None:
    """Raise AssertionError if ``rec`` violates the frozen schema."""
    missing = [k for k in RECORD_KEYS if k not in rec]
    assert not missing, f"record missing keys: {missing}"
    extra = [k for k in rec if k not in RECORD_KEYS]
    assert not extra, f"record has unexpected keys: {extra}"

    assert isinstance(rec["equipment_id"], str) and rec["equipment_id"]
    assert isinstance(rec["type"], str) and rec["type"]
    assert rec["customer_id"] is None or isinstance(rec["customer_id"], str)
    assert rec["site_id"] is None or isinstance(rec["site_id"], str)
    assert rec["health_score"] is None or (
        isinstance(rec["health_score"], int) and 0 <= rec["health_score"] <= 100
    )
    assert isinstance(rec["reasons"], list)
    assert all(isinstance(r, str) for r in rec["reasons"])
    assert rec["reallocatable"] is None or isinstance(rec["reallocatable"], bool)
    assert rec["demand_forecast"] is None or isinstance(rec["demand_forecast"], dict)
    assert rec["recommendation"] is None or isinstance(rec["recommendation"], dict)
