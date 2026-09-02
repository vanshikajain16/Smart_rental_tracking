"""Pydantic response models.

AssetRecord mirrors the project's Shared Contract exactly, so declaring it as a
``response_model`` also validates that what the API returns still matches the
contract.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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


class SignupRequest(BaseModel):
    """A new login linked to an existing Customer ID."""
    email: str
    password: str
    customer_id: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.fullmatch(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def _password_bounds(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(v.encode("utf-8")) > 72:
            # bcrypt only hashes the first 72 bytes; reject rather than
            # silently truncate.
            raise ValueError("password must be at most 72 bytes")
        return v

    @field_validator("customer_id")
    @classmethod
    def _trim_customer_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("customer_id is required")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer_id: str


class AuthedCustomer(BaseModel):
    customer_id: str
    email: str


class RenewalRiskCustomer(BaseModel):
    customer_id: str
    phone_number: str | None = None
    n_current_assets: int
    avg_health_score: float
    avg_health_all_cycles: float | None = None
    health_trend_slope_per_month: float
    trend_direction: str
    renewal_risk: bool
