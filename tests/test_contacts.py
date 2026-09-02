"""Connected Operators — Contact/Assignment CRUD + alert-log + contact dispatch.

    pytest -q tests/test_contacts.py

Runs against the real committed data; redirects every runtime CSV store
(contacts / assignments / alert_log / auth accounts) to a tmp dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_DIR = Path(__file__).resolve().parents[1] / "backend" / "api"
STAGE5_DIR = Path(__file__).resolve().parents[1] / "backend" / "stage5_customer_score"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(STAGE5_DIR))

import alert_log  # noqa: E402
import auth  # noqa: E402
import contacts as contacts_mod  # noqa: E402
from main import app  # noqa: E402

CID = "CUST01"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ACCOUNTS_CSV", tmp_path / "accounts.csv")
    monkeypatch.setattr(contacts_mod, "CONTACTS_CSV", tmp_path / "contacts.csv")
    monkeypatch.setattr(contacts_mod, "ASSIGNMENTS_CSV", tmp_path / "assignments.csv")
    monkeypatch.setattr(alert_log, "ALERT_LOG_CSV", tmp_path / "alert_log.csv")
    with TestClient(app) as c:
        c.post("/auth/signup", json={
            "email": "u@example.com", "password": "passw0rd123",
            "customer_id": CID,
        })
        tok = c.post("/auth/login", json={
            "email": "u@example.com", "password": "passw0rd123",
        }).json()["access_token"]
        assets = c.get(
            f"/customer/{CID}/assets",
            headers={"Authorization": f"Bearer {tok}"},
        ).json()
        yield c, {"Authorization": f"Bearer {tok}"}, assets[0]["equipment_id"], tmp_path


def _add(c, h, eq, **over):
    body = {"name": "Raj K.", "phone": "+9100112233", "role": "operator"}
    body.update(over)
    return c.post(f"/customer/{CID}/assets/{eq}/contacts", headers=h, json=body)


# --- CRUD -------------------------------------------------------------- #
def test_add_list_delete_roundtrip(env):
    c, h, eq, _ = env
    assert c.get(f"/customer/{CID}/assets/{eq}/contacts", headers=h).json() == []

    r = _add(c, h, eq)
    assert r.status_code == 201
    row = r.json()[0]
    assert row["name"] == "Raj K." and row["role"] == "operator"
    assert row["notify_due_date"] is True and row["notify_demand"] is False

    got = c.get(f"/customer/{CID}/assets/{eq}/contacts", headers=h).json()
    assert len(got) == 1
    cid = got[0]["contact_id"]

    d = c.delete(f"/customer/{CID}/assets/{eq}/contacts/{cid}", headers=h)
    assert d.status_code == 200 and d.json() == []


def test_four_contact_cap(env):
    c, h, eq, _ = env
    for i in range(4):
        assert _add(c, h, eq, name=f"P{i}", phone=f"+910000{i}").status_code == 201
    over = _add(c, h, eq, name="X", phone="+915555")
    assert over.status_code == 409
    assert "maximum of 4" in over.json()["detail"]


def test_reuses_contact_row_for_same_phone(env):
    c, h, eq, tmp = env
    _add(c, h, eq, phone="+9199")
    # same person, second asset
    assets = c.get(f"/customer/{CID}/assets", headers=h).json()
    eq2 = next(a["equipment_id"] for a in assets if a["equipment_id"] != eq)
    _add(c, h, eq2, phone="+9199")
    contact_rows = (tmp / "contacts.csv").read_text().strip().splitlines()
    assert len(contact_rows) == 2  # header + one contact, not two


def test_cannot_touch_another_customers_asset(env):
    c, h, eq, _ = env
    r = c.post("/customer/CUST02/assets/EQX1002/contacts", headers=h,
               json={"name": "Y", "phone": "+91"})
    assert r.status_code == 403


def test_requires_auth(env):
    c, _h, eq, _ = env
    assert c.get(f"/customer/{CID}/assets/{eq}/contacts").status_code == 401


def test_unknown_equipment_is_404(env):
    c, h, _eq, _ = env
    r = c.get(f"/customer/{CID}/assets/NOPE999/contacts", headers=h)
    assert r.status_code == 404


# --- dispatch + alert log ------------------------------------------ #
def test_run_logs_customer_and_notifies_opted_in_contact(env):
    c, h, _eq, tmp = env
    import sms_alerts
    from schemas import ContactCreate

    # EQX1063 is still checked out to CUST01 with a due reminder at TODAY, but
    # its *current* pipeline record isn't CUST01's, so it isn't in
    # assets_for_customer() and the endpoint would 404. Seed via the store.
    due_eq = "EQX1063"  # due 2025-11-26, 3-day (High-tier) lead
    contacts_mod.create_contact_and_assignment(
        customer_id=CID, equipment_id=due_eq,
        body=ContactCreate(name="Due D.", phone="+9100abc",
                           notify_due_date=True, notify_health=False),
    )
    contacts_mod.create_contact_and_assignment(
        customer_id=CID, equipment_id=due_eq,
        body=ContactCreate(name="Silent S.", phone="+9100xyz",
                           notify_due_date=False, notify_health=False),
    )

    sent = sms_alerts.run()
    assert len(sent) == 1  # customer-facing reminder count unchanged

    log = alert_log.read_alert_log(due_eq)
    kinds = {(r["recipient_type"], r["alert_type"]) for r in log}
    assert ("customer", "due_date") in kinds
    assert ("contact", "due_date") in kinds
    # the notify_due_date=False contact was not messaged
    contact_phones = {r["phone"] for r in log if r["recipient_type"] == "contact"}
    assert "+9100abc" in contact_phones and "+9100xyz" not in contact_phones


def test_health_alerts_never_include_demand(env):
    c, h, _eq, tmp = env
    import sms_alerts

    flagged_eq = "EQX1045"  # CUST04-owned, Stage 1 flagged
    # (added via the store directly — different owner, endpoint would 403)
    from schemas import ContactCreate
    contacts_mod.create_contact_and_assignment(
        customer_id="CUST04", equipment_id=flagged_eq,
        body=ContactCreate(name="H", phone="+9107777", role="site lead",
                           notify_due_date=False, notify_health=True,
                           notify_demand=True),
    )
    sms_alerts.send_health_alerts()

    log = alert_log.read_alert_log(flagged_eq)
    assert any(r["recipient_type"] == "contact" for r in log)
    for r in log:
        assert "demand" not in r["message"].lower()
        assert "move to" not in r["message"].lower()
