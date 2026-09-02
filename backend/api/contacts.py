"""Connected Operators - per-asset contacts (Contact + Assignment).

A customer attaches up to 4 people (Contacts) to a SPECIFIC asset. Each
Contact<->Asset link is an Assignment with three independent notify switches:
due-date reminders, health/idle alerts, and demand/reallocation insights
(the last is OFF by default and stays a no-op in dispatch this iteration -
see sms_alerts.py).

Two CSV stores (created on first write, same convention as
customer_accounts.csv):
    data/processed/contacts.csv     contact_id, customer_id, name, phone, email
    data/processed/assignments.csv  assignment_id, equipment_id, contact_id,
                                    role, notify_due_date, notify_health,
                                    notify_demand, added_by, created_at

The store helpers here are import-safe (no FastAPI needed to call them) so
Stage 5's sms_alerts.py can reuse them for dispatch.
"""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

import auth
import data_access as da
from schemas import Contact, ContactCreate, ContactWithAssignment

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTACTS_CSV = REPO_ROOT / "data" / "processed" / "contacts.csv"
ASSIGNMENTS_CSV = REPO_ROOT / "data" / "processed" / "assignments.csv"

CONTACT_FIELDS = ["contact_id", "customer_id", "name", "phone", "email"]
ASSIGNMENT_FIELDS = [
    "assignment_id", "equipment_id", "contact_id", "role",
    "notify_due_date", "notify_health", "notify_demand",
    "added_by", "created_at",
]

MAX_CONTACTS_PER_ASSET = 4
_BOOL_FIELDS = {"notify_due_date", "notify_health", "notify_demand"}

_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# CSV primitives
# --------------------------------------------------------------------------- #
def _read(path: Path, fields: list[str]) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for b in _BOOL_FIELDS & r.keys():
            r[b] = str(r[b]).strip().lower() == "true"
    return rows


def _write_all(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})


# --------------------------------------------------------------------------- #
# Store queries (import-safe - used by sms_alerts.py too)
# --------------------------------------------------------------------------- #
def all_contacts() -> list[dict]:
    return _read(CONTACTS_CSV, CONTACT_FIELDS)


def all_assignments() -> list[dict]:
    return _read(ASSIGNMENTS_CSV, ASSIGNMENT_FIELDS)


def contact_by_id(contact_id: str) -> dict | None:
    return next((c for c in all_contacts() if c["contact_id"] == contact_id),
               None)


def assignments_for_equipment(equipment_id: str) -> list[dict]:
    return [a for a in all_assignments() if a["equipment_id"] == equipment_id]


def contacts_with_assignments(equipment_id: str) -> list[dict]:
    """Join: one ContactWithAssignment-shaped dict per contact on this asset."""
    by_id = {c["contact_id"]: c for c in all_contacts()}
    out = []
    for a in assignments_for_equipment(equipment_id):
        c = by_id.get(a["contact_id"])
        if not c:
            continue
        out.append({
            "contact_id": c["contact_id"],
            "name": c["name"],
            "phone": c["phone"],
            "email": c.get("email") or None,
            "role": a["role"],
            "notify_due_date": bool(a["notify_due_date"]),
            "notify_health": bool(a["notify_health"]),
            "notify_demand": bool(a["notify_demand"]),
            "assignment_id": a["assignment_id"],
        })
    return out


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def create_contact_and_assignment(
    *, customer_id: str, equipment_id: str, body: ContactCreate,
) -> dict:
    """Create (or reuse) the Contact, then link it to this asset. Raises
    ValueError on the 4-per-asset cap or a duplicate link."""
    phone = body.phone.strip()
    with _lock:
        contacts = _read(CONTACTS_CSV, CONTACT_FIELDS)
        assignments = _read(ASSIGNMENTS_CSV, ASSIGNMENT_FIELDS)

        existing_links = [a for a in assignments
                          if a["equipment_id"] == equipment_id]
        if len(existing_links) >= MAX_CONTACTS_PER_ASSET:
            raise ValueError(
                f"this asset already has the maximum of "
                f"{MAX_CONTACTS_PER_ASSET} connected contacts"
            )

        # reuse a contact row for the same person (phone + customer_id)
        contact = next(
            (c for c in contacts
             if c["customer_id"] == customer_id
             and c["phone"].strip() == phone),
            None,
        )
        if contact is None:
            contact = {
                "contact_id": uuid4().hex[:8],
                "customer_id": customer_id,
                "name": body.name.strip(),
                "phone": phone,
                "email": (body.email or "").strip(),
            }
            contacts.append(contact)
            _write_all(CONTACTS_CSV, CONTACT_FIELDS, contacts)

        if any(a["contact_id"] == contact["contact_id"]
               for a in existing_links):
            raise ValueError("this contact is already linked to this asset")

        assignment = {
            "assignment_id": uuid4().hex[:8],
            "equipment_id": equipment_id,
            "contact_id": contact["contact_id"],
            "role": body.role.strip() or "operator",
            "notify_due_date": str(bool(body.notify_due_date)),
            "notify_health": str(bool(body.notify_health)),
            "notify_demand": str(bool(body.notify_demand)),
            "added_by": customer_id,
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }
        assignments.append(assignment)
        _write_all(ASSIGNMENTS_CSV, ASSIGNMENT_FIELDS, assignments)

    return {"contact": contact, "assignment": assignment}


def remove_assignment(equipment_id: str, contact_id: str) -> bool:
    """Drop the Contact<->Asset link. The Contact row is kept (it may be
    linked to other assets). Returns False if there was no such link."""
    with _lock:
        assignments = _read(ASSIGNMENTS_CSV, ASSIGNMENT_FIELDS)
        keep = [a for a in assignments
                if not (a["equipment_id"] == equipment_id
                        and a["contact_id"] == contact_id)]
        if len(keep) == len(assignments):
            return False
        _write_all(ASSIGNMENTS_CSV, ASSIGNMENT_FIELDS, keep)
    return True


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
contacts_router = APIRouter(prefix="/customer", tags=["contacts"])


def _authorize_own_asset(customer_id: str, equipment_id: str,
                         caller_id: str) -> None:
    """Same boundary as customer_routes: caller must be this customer, and the
    equipment must be one of their own assets."""
    if customer_id != caller_id:
        raise HTTPException(status_code=403,
                            detail="you can only access your own data")
    if customer_id not in da.customer_ids():
        raise HTTPException(status_code=404,
                            detail=f"unknown customer_id '{customer_id}'")
    owned = {str(a.get("equipment_id"))
             for a in da.assets_for_customer(customer_id)}
    if equipment_id not in owned:
        raise HTTPException(
            status_code=404,
            detail=f"equipment '{equipment_id}' is not one of this "
                   f"customer's assets",
        )


@contacts_router.get(
    "/{customer_id}/assets/{equipment_id}/contacts",
    response_model=list[ContactWithAssignment],
)
def list_asset_contacts(customer_id: str, equipment_id: str,
                        caller_id: str = Depends(auth.get_current_customer)):
    _authorize_own_asset(customer_id, equipment_id, caller_id)
    return contacts_with_assignments(equipment_id)


@contacts_router.post(
    "/{customer_id}/assets/{equipment_id}/contacts",
    response_model=list[ContactWithAssignment],
    status_code=201,
)
def add_asset_contact(customer_id: str, equipment_id: str, body: ContactCreate,
                      caller_id: str = Depends(auth.get_current_customer)):
    _authorize_own_asset(customer_id, equipment_id, caller_id)
    if not body.name.strip() or not body.phone.strip():
        raise HTTPException(status_code=422,
                            detail="name and phone are required")
    try:
        create_contact_and_assignment(
            customer_id=customer_id, equipment_id=equipment_id, body=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return contacts_with_assignments(equipment_id)


@contacts_router.delete(
    "/{customer_id}/assets/{equipment_id}/contacts/{contact_id}",
    response_model=list[ContactWithAssignment],
)
def delete_asset_contact(customer_id: str, equipment_id: str, contact_id: str,
                         caller_id: str = Depends(auth.get_current_customer)):
    _authorize_own_asset(customer_id, equipment_id, caller_id)
    if not remove_assignment(equipment_id, contact_id):
        raise HTTPException(
            status_code=404,
            detail=f"contact '{contact_id}' is not linked to this asset",
        )
    return contacts_with_assignments(equipment_id)
