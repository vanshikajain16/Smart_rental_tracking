"""Customer authentication + access-control tests.

    pytest -q tests/test_auth.py

Uses the real customers.csv / pipeline output (they ship with the repo) but
redirects the account store to a tmp CSV so signups don't touch
data/processed/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "backend" / "api"
sys.path.insert(0, str(API_DIR))

import auth  # noqa: E402
from main import app  # noqa: E402

# two real ids from data/processed/customers.csv
CID = "CUST02"
OTHER_CID = "CUST03"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ACCOUNTS_CSV", tmp_path / "customer_accounts.csv")
    with TestClient(app) as c:
        yield c


def _signup(client, email="a@example.com", password="hunter2!!", cid=CID):
    return client.post(
        "/auth/signup",
        json={"email": email, "password": password, "customer_id": cid},
    )


# --- token helpers ---------------------------------------------------- #
def test_token_round_trip():
    tok = auth.create_access_token("CUST09", expires_minutes=5)
    assert auth.decode_access_token(tok) == "CUST09"


def test_decode_rejects_garbage():
    with pytest.raises(Exception):
        auth.decode_access_token("not.a.jwt")


# --- signup --------------------------------------------------------- #
def test_signup_creates_account(client, tmp_path):
    r = _signup(client)
    assert r.status_code == 200
    assert r.json() == {"message": "account created"}
    rows = (tmp_path / "customer_accounts.csv").read_text().splitlines()
    assert rows[0] == "email,hashed_password,customer_id,created_at"
    assert rows[1].startswith("a@example.com,")
    assert ",CUST02," in rows[1]


def test_signup_hashes_the_password(client, tmp_path):
    _signup(client, password="plaintext-secret")
    body = (tmp_path / "customer_accounts.csv").read_text()
    assert "plaintext-secret" not in body
    assert "$2b$" in body  # bcrypt hash marker


def test_signup_rejects_unknown_customer_id(client):
    r = _signup(client, cid="CUST_NOPE")
    assert r.status_code == 400
    assert "not a known customer" in r.json()["detail"]


def test_signup_unknown_id_writes_nothing(client, tmp_path):
    _signup(client, cid="CUST_NOPE")
    csv_path = tmp_path / "customer_accounts.csv"
    # header-only file at most, never a data row
    assert not csv_path.exists() or len(csv_path.read_text().splitlines()) <= 1


def test_signup_duplicate_email_conflicts(client):
    assert _signup(client).status_code == 200
    r = _signup(client, cid=OTHER_CID)  # same email, different id
    assert r.status_code == 409


def test_signup_customer_id_already_linked_conflicts(client):
    assert _signup(client, email="first@example.com").status_code == 200
    r = _signup(client, email="second@example.com")  # same id
    assert r.status_code == 409


# --- login -------------------------------------------------------- #
def test_login_returns_bearer_token(client):
    _signup(client, email="u@example.com", password="correct-horse")
    r = client.post(
        "/auth/login",
        json={"email": "u@example.com", "password": "correct-horse"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["customer_id"] == CID
    assert auth.decode_access_token(body["access_token"]) == CID


def test_login_wrong_password_is_401_generic(client):
    _signup(client, email="u@example.com", password="correct-horse")
    r = client.post(
        "/auth/login",
        json={"email": "u@example.com", "password": "wrong-password"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


def test_login_unknown_email_is_401_generic(client):
    r = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "whatever!!"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


# --- check-email (UX hint only) --------------------------------- #
def test_check_email_reports_existence(client):
    assert client.get(
        "/auth/check-email", params={"email": "nobody@example.com"}
    ).json() == {"exists": False}

    _signup(client, email="somebody@example.com")

    assert client.get(
        "/auth/check-email", params={"email": "somebody@example.com"}
    ).json() == {"exists": True}
    # same case-folding as the login lookup
    assert client.get(
        "/auth/check-email", params={"email": "SOMEBODY@Example.com"}
    ).json() == {"exists": True}


# --- protected customer routes -------------------------------- #
def _token(client, **kw):
    _signup(client, **kw)
    email = kw.get("email", "a@example.com")
    password = kw.get("password", "hunter2!!")
    return client.post(
        "/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]


def test_customer_assets_requires_a_token(client):
    assert client.get(f"/customer/{CID}/assets").status_code == 401


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
        assert r.json()["detail"] == "you can only access your own data"


def test_garbage_token_is_401(client):
    r = client.get(
        f"/customer/{CID}/assets",
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert r.status_code == 401


def test_dealer_routes_stay_open(client):
    assert client.get("/dealer/customers").status_code == 200


# --------------------------------------------------------------------------- #
# The five-point checklist for the customer-login task, in one walkthrough.
# --------------------------------------------------------------------------- #
def test_customer_auth_end_to_end(client):
    # 1. signup succeeds for a real Customer ID
    ok = client.post(
        "/auth/signup",
        json={"email": "me@example.com", "password": "s3cret-pass",
              "customer_id": CID},
    )
    assert ok.status_code == 200

    # 2. signup fails for a Customer ID not in customers.csv
    bad = client.post(
        "/auth/signup",
        json={"email": "x@example.com", "password": "s3cret-pass",
              "customer_id": "CUST_NOT_REAL"},
    )
    assert bad.status_code == 400

    # 3. login returns a token
    login = client.post(
        "/auth/login",
        json={"email": "me@example.com", "password": "s3cret-pass"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token

    # 4. no token -> 401
    assert client.get(f"/customer/{CID}/assets").status_code == 401

    # 5. another customer's valid token -> 403
    other = client.post(
        "/auth/signup",
        json={"email": "other@example.com", "password": "s3cret-pass",
              "customer_id": OTHER_CID},
    )
    assert other.status_code == 200
    other_token = client.post(
        "/auth/login",
        json={"email": "other@example.com", "password": "s3cret-pass"},
    ).json()["access_token"]
    forbidden = client.get(
        f"/customer/{CID}/assets",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden.status_code == 403

    # sanity: own token still works
    own = client.get(
        f"/customer/{CID}/assets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert own.status_code == 200
