"""Pydantic response models.

AssetRecord mirrors the project's Shared Contract exactly, so declaring it as a
``response_model`` also validates that what the API returns still matches the
contract.
"""
from __future__ import annotations

from pydantic import BaseModel


class DemandForecast(BaseModel):
    site_id: str | None = None
    type: str | None = None
    predicted_need_days: int | None = None


class Recommendation(BaseModel):
    action: str
    from_site: str | None = None
    to_site: str | None = None
    reason: str


class AssetRecord(BaseModel):
    equipment_id: str
    type: str
    customer_id: str | None = None
    site_id: str | None = None
    health_score: int | None = None
    reasons: list[str] = []
    reallocatable: bool | None = None
    demand_forecast: DemandForecast | None = None
    recommendation: Recommendation | None = None


class DealerCustomer(BaseModel):
    customer_id: str
    phone_number: str | None = None
    reliability_score: int | None = None
    risk_tier: str | None = None
    n_assets: int
    avg_health_score: float | None = None
    trend_direction: str | None = None
    health_trend_slope_per_month: float | None = None
    renewal_risk: bool = False


class SmsReminder(BaseModel):
    customer_id: str
    phone_number: str | None = None
    equipment_id: str
    type: str
    site_id: str | None = None
    expected_return_date: str
    lead_days: int
    risk_tier: str | None = None
    message: str


class RenewalRiskCustomer(BaseModel):
    customer_id: str
    phone_number: str | None = None
    n_current_assets: int
    avg_health_score: float
    avg_health_all_cycles: float | None = None
    health_trend_slope_per_month: float
    trend_direction: str
    renewal_risk: bool
