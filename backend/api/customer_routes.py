"""Customer-facing endpoints.

GET /customer/{customer_id}/assets   - that customer's per-asset records from
                                       Stage 4's pipeline output (Shared
                                       Contract shape).
GET /customer/{customer_id}/alerts   - same, filtered to assets whose latest
                                       cycle is is_flagged = true (Stage 1).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import data_access as da
from schemas import AssetRecord, SmsReminder

router = APIRouter(prefix="/customer", tags=["customer"])


def _known_customer(customer_id: str) -> None:
    if customer_id not in da.customer_ids():
        raise HTTPException(status_code=404,
                            detail=f"unknown customer_id '{customer_id}'")


@router.get("/{customer_id}/assets", response_model=list[AssetRecord])
def customer_assets(customer_id: str):
    _known_customer(customer_id)
    return da.assets_for_customer(customer_id)


@router.get("/{customer_id}/alerts", response_model=list[AssetRecord])
def customer_alerts(customer_id: str):
    _known_customer(customer_id)
    flagged = da.latest_cycle_is_flagged()
    return [a for a in da.assets_for_customer(customer_id)
            if flagged.get(str(a.get("equipment_id")), False)]


@router.get("/{customer_id}/sms-reminders", response_model=list[SmsReminder])
def customer_sms_reminders(customer_id: str):
    """Pending return-reminder SMS for this customer (Stage 5 sms_alerts logic)."""
    _known_customer(customer_id)
    return da.sms_reminders_for_customer(customer_id)
