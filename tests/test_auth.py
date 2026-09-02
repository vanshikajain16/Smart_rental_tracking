"""Customer authentication + access-control tests.

    pytest -q tests/test_auth.py

Uses the real customers.csv / pipeline output (they ship with the repo) but
redirects the auth-user store to a tmp file so signups don't touch
data/processed/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "backend" / "api"
sys.path.insert(0, str(API_DIR))

import auth_store  # noqa: E402
import data_access as da  # noqa: E402
from main import app  # noqa: E402

# two real ids from data/processed/customers.csv
CID = "CUST02"
OTHER_CID = "CUST03"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store, "AUTH_USERS_JSON", tmp_path / "auth_users.json")
    with TestClient(app) as c:
        yield c


def _signup(client, email="a@example.com", password="hunter2!!", cid=CID):
    return client.post(
        "/auth/signup",
        json={"email": email, "password": password, "customer_id": cid},
    )


# --- signup ------------------------------------------------------------- #
def test_signup_links_existing_customer_and_returns_token(client):
    r = _signup(client)
    assert r.status_code == 201
    body = r.json()
    assert body["customer_id"] == CID
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_signup_rejects_unknown_customer_id(client):
    r = _signup(client, cid="CUST_NOPE")
    assert r.status_code == 400
    assert "not a known customer" in r.json()["detail"]


def test_signup_unknown_id_is_never_stored(client, tmp_path):
    _signup(client, cid="CUST_NOPE")
    assert not (tmp_path / "auth_users.json").exists()


def test_signup_duplicate_email_conflicts(client):
    assert _signup(client).status_code == 201
    r = _signup(client, cid=OTHER_CID)  # same email, different id
    assert r.status_code == 409


def test_signup_customer_id_already_linked_conflicts(client):
    assert _signup(client, email="first@example.com").status_code == 201
    r = _signup(client, email="second@example.com")  # same id
    assert r.status_code == 409
    assert CID in r.json()["detail"]


def test_signup_short_password_is_422(client):
    r = _signup(client, password="short")
    assert r.status_code == 422


# --- login ------------------------------------------------------------- #
def test_login_returns_token_for_good_credentials(client):
    _signup(client, email="u@example.com", password="correct-horse")
    r = client.post(
        "/auth/login",
        json={"email": "u@example.com", "password": "correct-horse"},
    )
    assert r.status_code == 200
    assert r.json()["customer_id"] == CID


def test_login_wrong_password_is_401(client):
    _signup(client, email="u@example.com", password="correct-horse")
    r = client.post(
        "/auth/login",
        json={"email": "u@example.com", "password": "nope-nope-nope"},
    )
    assert r.status_code == 401


def test_login_unknown_email_is_401(client):
    r = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "whatever!!"},
    )
    assert r.status_code == 401


# --- protected customer routes --------------------------------------- #
def _token(client, **kw):
    return _signup(client, **kw).json()["access_token"]


def test_customer_assets_requires_a_token(client):
    r = client.get(f"/customer/{CID}/assets")
    assert r.status_code == 401


def test_customer_assets_served_with_own_token(client):
    tok = _token(client)
    r = client.get(
        f"/customer/{CID}/assets", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_customer_cannot_read_another_customers_data(client):
    tok = _token(client)  # token for CID
    for path in ("assets", "alerts", "sms-reminders"):
        r = client.get(
            f"/customer/{OTHER_CID}/{path}",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 403, path


def test_garbage_token_is_401(client):
    r = client.get(
        f"/customer/{CID}/assets",
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert r.status_code == 401


def test_me_echoes_token_identity(client):
    tok = _token(client, email="who@example.com")
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json() == {"customer_id": CID, "email": "who@example.com"}


def test_dealer_routes_stay_open(client):
    assert client.get("/dealer/customers").status_code == 200
