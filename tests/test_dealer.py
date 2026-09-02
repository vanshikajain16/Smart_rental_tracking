"""Dealer drill-down + retroactive activity feed tests.

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
CATEGORIES = {"flag", "penalty", "sms_reminder"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- drill-down --------------------------------------------------------- #
def test_customer_detail_has_aggregate_and_assets(client):
    r = client.get(f"/dealer/customers/{CID}")
    assert r.status_code == 200
    body = r.json()
    assert body["customer_id"] == CID
    assert body["n_assets"] == len(body["assets"])
    assert body["n_assets"] > 0
    for a in body["assets"]:
        assert a["customer_id"] == CID
        assert a["equipment_id"]


def test_customer_detail_unknown_id_is_404(client):
    assert client.get("/dealer/customers/CUST_NOPE").status_code == 404


# --- activity feed --------------------------------------------------- #
def test_activity_feed_is_reconstructed_and_sorted(client):
    events = client.get("/dealer/activity?limit=1000").json()
    assert len(events) > 0
    assert {e["category"] for e in events} <= CATEGORIES
    # Stage 1 flags and penalty rows are both reconstructed
    assert {"flag", "penalty"} <= {e["category"] for e in events}
    # newest first
    dates = [e["date"] for e in events]
    assert dates == sorted(dates, reverse=True)


def test_activity_feed_respects_limit(client):
    assert len(client.get("/dealer/activity?limit=5").json()) == 5


def test_activity_feed_customer_filter(client):
    events = client.get(f"/dealer/activity?customer_id={CID}&limit=1000").json()
    assert len(events) > 0
    assert all(e["customer_id"] == CID for e in events)
    # a subset of the dealer-wide feed
    everything = client.get("/dealer/activity?limit=2000").json()
    assert len(events) < len(everything)


def test_activity_feed_still_open_when_no_auth(client):
    # dealer side stays unauthenticated
    assert client.get("/dealer/activity").status_code == 200
