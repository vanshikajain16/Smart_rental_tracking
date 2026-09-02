"""Dealer summary / drill-down / retroactive activity-feed tests.

    pytest -q tests/test_dealer.py

Runs against the real pipeline artifacts that ship with the repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "backend" / "api"
sys.path.insert(0, str(API_DIR))

from main import app  # noqa: E402

CID = "CUST04"  # renewal-risk customer with 4 current assets
EVENT_TYPES = {"high_risk", "flag", "penalty", "sms_reminder"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- /dealer/summary -------------------------------------------------- #
def test_summary_returns_valid_stats(client):
    r = client.get("/dealer/summary")
    assert r.status_code == 200
    s = r.json()
    assert set(s) == {
        "total_customers", "total_assets", "avg_fleet_health_score",
        "high_risk_count", "pending_sms_count", "unpaid_penalty_count",
    }
    assert s["total_customers"] > 0
    assert s["total_assets"] > 0
    assert 0 <= s["avg_fleet_health_score"] <= 100
    for k in ("high_risk_count", "pending_sms_count", "unpaid_penalty_count"):
        assert isinstance(s[k], int) and s[k] >= 0
    assert s["high_risk_count"] <= s["total_customers"]


def test_summary_matches_customer_list(client):
    s = client.get("/dealer/summary").json()
    custs = client.get("/dealer/customers").json()
    assert s["total_customers"] == len(custs)
    assert s["total_assets"] == sum(c["n_assets"] for c in custs)
    assert s["high_risk_count"] == sum(
        1 for c in custs if c["risk_tier"] == "High")


# --- /dealer/activity-feed --------------------------------------- #
def test_activity_feed_is_valid_and_sorted(client):
    r = client.get("/dealer/activity-feed")
    assert r.status_code == 200
    feed = r.json()
    assert 0 < len(feed) <= 50
    for e in feed:
        assert set(e) == {"date", "type", "customer_id", "message"}
        assert e["type"] in EVENT_TYPES
        assert e["message"]
    dates = [e["date"] for e in feed]
    assert dates == sorted(dates, reverse=True)


def test_activity_feed_reconstructs_multiple_sources(client):
    kinds = {e["type"] for e in client.get("/dealer/activity-feed").json()}
    # flags and penalties are both plentiful in the dataset
    assert {"flag", "penalty"} <= kinds


# --- drill-down (unchanged) ------------------------------------ #
def test_customer_detail_has_aggregate_and_assets(client):
    r = client.get(f"/dealer/customers/{CID}")
    assert r.status_code == 200
    body = r.json()
    assert body["customer_id"] == CID
    assert body["n_assets"] == len(body["assets"]) > 0
    assert all(a["customer_id"] == CID for a in body["assets"])


def test_customer_detail_unknown_id_is_404(client):
    assert client.get("/dealer/customers/CUST_NOPE").status_code == 404


def test_dealer_customer_assets_route(client):
    r = client.get(f"/dealer/customer/{CID}/assets")
    assert r.status_code == 200
    assets = r.json()
    assert len(assets) > 0
    for a in assets:
        assert a["customer_id"] == CID
        assert set(a) >= {
            "equipment_id", "type", "health_score", "reasons",
            "reallocatable", "recommendation",
        }
    # same payload the drill-down embeds
    assert assets == client.get(f"/dealer/customers/{CID}").json()["assets"]


def test_dealer_customer_assets_unknown_id_is_404(client):
    r = client.get("/dealer/customer/CUST_NOPE/assets")
    assert r.status_code == 404
    assert "CUST_NOPE" in r.json()["detail"]


def test_dealer_side_stays_unauthenticated(client):
    for path in ("/dealer/summary", "/dealer/activity-feed",
                 "/dealer/customers", f"/dealer/customers/{CID}"):
        assert client.get(path).status_code == 200, path
