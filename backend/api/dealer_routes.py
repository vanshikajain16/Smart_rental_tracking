"""Dealer-facing endpoints.

GET /dealer/customers               - every customer from customers.csv with
                                      Reliability Score, Risk Tier (Stage 5) and
                                      the aggregated average health score of
                                      their current assets (Stage 1-4 output).
GET /dealer/customers/{customer_id} - drill-down: that customer's aggregate plus
                                      their current per-asset records.
GET /dealer/customer/{customer_id}/assets
                                    - just the per-asset detail for one customer
                                      (same shape as the customer-side route,
                                      no auth - dealer view).
GET /dealer/summary                 - headline numbers for the dashboard.
GET /dealer/renewal-risk            - just the customers flagged renewal_risk in
                                      Stage 4's dealer-level aggregate.
GET /dealer/activity-feed           - retroactive activity feed (High-risk
                                      customers, Stage 1 flags, penalty_charged
                                      rows, SMS reminders), newest first, top 50.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import data_access as da
from schemas import (
    ActivityEvent,
    AssetRecord,
    DealerCustomer,
    DealerCustomerDetail,
    RenewalRiskCustomer,
    SummaryStats,
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


@router.get("/customer/{customer_id}/assets", response_model=list[AssetRecord])
def dealer_customer_assets(customer_id: str):
    """The same per-asset detail as GET /customer/{customer_id}/assets, but on
    the dealer side (no auth) - reuses data_access.assets_for_customer."""
    if customer_id not in da.customer_ids():
        raise HTTPException(status_code=404,
                            detail=f"unknown customer_id '{customer_id}'")
    return da.assets_for_customer(customer_id)


@router.get("/summary", response_model=SummaryStats)
def dealer_summary():
    counts = da.assets_count_by_customer()
    health = da.avg_health_by_customer()
    customers = da.customers_table()

    health_vals = [v for v in health.values() if v is not None]
    return SummaryStats(
        total_customers=len(customers),
        total_assets=sum(counts.values()),
        avg_fleet_health_score=(round(sum(health_vals) / len(health_vals), 1)
                                if health_vals else None),
        high_risk_count=sum(1 for c in customers.values()
                            if c.get("risk_tier") == "High"),
        pending_sms_count=sum(len(da.sms_reminders_for_customer(cid))
                              for cid in customers),
        unpaid_penalty_count=da.unpaid_penalty_count(),
    )


@router.get("/renewal-risk", response_model=list[RenewalRiskCustomer])
def dealer_renewal_risk():
    return [c for c in da.customer_aggregate() if c.get("renewal_risk")]


@router.get("/activity-feed", response_model=list[ActivityEvent])
def dealer_activity_feed():
    return da.activity_events(limit=50)
