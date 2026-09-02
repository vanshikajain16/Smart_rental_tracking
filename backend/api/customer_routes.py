"""Customer-facing endpoints.

All three require a Bearer token (see auth.py) and only ever serve the caller's
own data: asking for another customer_id is a 403, so the token's `sub` is the
real access-control boundary, not the path parameter.

GET /customer/{customer_id}/assets   - that customer's per-asset records from
                                       Stage 4's pipeline output (Shared
                                       Contract shape).
GET /customer/{customer_id}/alerts   - same, filtered to assets whose latest
                                       cycle is is_flagged = true (Stage 1).
GET /customer/{customer_id}/sms-reminders - pending return-reminder SMS
                                       (Stage 5 sms_alerts logic).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import auth
import data_access as da
from schemas import AssetRecord, SmsReminder

router = APIRouter(prefix="/customer", tags=["customer"])


def _known_customer(customer_id: str) -> None:
    if customer_id not in da.customer_ids():
        raise HTTPException(status_code=404,
                            detail=f"unknown customer_id '{customer_id}'")


def _authorize(path_customer_id: str, caller_id: str) -> None:
    """Refuse any id that isn't the caller's own. Checked before existence so
    the route can't be used to probe which Customer IDs exist."""
    if path_customer_id != caller_id:
        raise HTTPException(
            status_code=403,
            detail="you can only access your own data",
        )
    _known_customer(path_customer_id)


@router.get("/{customer_id}/assets", response_model=list[AssetRecord])
def customer_assets(customer_id: str,
                    caller_id: str = Depends(auth.get_current_customer)):
    _authorize(customer_id, caller_id)
    return da.assets_for_customer(customer_id)


@router.get("/{customer_id}/alerts", response_model=list[AssetRecord])
def customer_alerts(customer_id: str,
                    caller_id: str = Depends(auth.get_current_customer)):
    _authorize(customer_id, caller_id)
    flagged = da.latest_cycle_is_flagged()
    return [a for a in da.assets_for_customer(customer_id)
            if flagged.get(str(a.get("equipment_id")), False)]


@router.get("/{customer_id}/sms-reminders", response_model=list[SmsReminder])
def customer_sms_reminders(customer_id: str,
                           caller_id: str = Depends(auth.get_current_customer)):
    """Pending return-reminder SMS for this customer (Stage 5 sms_alerts logic)."""
    _authorize(customer_id, caller_id)
    return da.sms_reminders_for_customer(customer_id)
