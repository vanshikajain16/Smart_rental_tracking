"""Dealer-facing endpoints.

GET /dealer/customers      - every customer from customers.csv with Reliability
                             Score, Risk Tier (Stage 5) and the aggregated
                             average health score of their current assets
                             (from the Stage 1-4 pipeline output).
GET /dealer/renewal-risk   - just the customers flagged renewal_risk in Stage
                             4's dealer-level aggregate.
"""
from __future__ import annotations

from fastapi import APIRouter

import data_access as da
from schemas import DealerCustomer, RenewalRiskCustomer

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


@router.get("/renewal-risk", response_model=list[RenewalRiskCustomer])
def dealer_renewal_risk():
    return [c for c in da.customer_aggregate() if c.get("renewal_risk")]
