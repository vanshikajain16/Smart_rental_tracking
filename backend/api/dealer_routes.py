"""Dealer-facing endpoints.

GET /dealer/customers               - every customer from customers.csv with
                                      Reliability Score, Risk Tier (Stage 5) and
                                      the aggregated average health score of
                                      their current assets (Stage 1-4 output).
GET /dealer/customers/{customer_id} - drill-down: that customer's aggregate plus
                                      their current per-asset records.
GET /dealer/renewal-risk            - just the customers flagged renewal_risk in
                                      Stage 4's dealer-level aggregate.
GET /dealer/activity                - retroactive activity feed (Stage 1 flags,
                                      penalty_charged rows, pending SMS
                                      reminders), newest first; optional
                                      ?customer_id= filter.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import data_access as da
from schemas import (
    ActivityEvent,
    DealerCustomer,
    DealerCustomerDetail,
    RenewalRiskCustomer,
)

router = APIRouter(prefix="/dealer", tags=["dealer"])


@router.get("/customers", response_model=list[DealerCustomer])
def dealer_customers():
    customers = da.customers_table()
    avg_health = da.avg_health_by_customer()
    counts = da.assets_count_by_customer()
    agg = da.customer_aggregate_by_id()

    rows = []
    for cid, info in sorted(customers.items()):
        a = agg.get(cid, {})
        rows.append(DealerCustomer(
            customer_id=cid,
            phone_number=info["phone_number"],
            reliability_score=info["reliability_score"],
            risk_tier=info["risk_tier"],
            n_assets=counts.get(cid, 0),
            avg_health_score=avg_health.get(cid, a.get("avg_health_score")),
            trend_direction=a.get("trend_direction"),
            health_trend_slope_per_month=a.get("health_trend_slope_per_month"),
            renewal_risk=bool(a.get("renewal_risk", False)),
        ))
    return rows


@router.get("/customers/{customer_id}", response_model=DealerCustomerDetail)
def dealer_customer_detail(customer_id: str):
    if customer_id not in da.customer_ids():
        raise HTTPException(status_code=404,
                            detail=f"unknown customer_id '{customer_id}'")
    return da.dealer_customer_detail(customer_id)


@router.get("/renewal-risk", response_model=list[RenewalRiskCustomer])
def dealer_renewal_risk():
    return [c for c in da.customer_aggregate() if c.get("renewal_risk")]


@router.get("/activity", response_model=list[ActivityEvent])
def dealer_activity(
    customer_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
):
    return da.activity_events(customer_id=customer_id, limit=limit)
