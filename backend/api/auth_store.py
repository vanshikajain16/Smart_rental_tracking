"""Tiny JSON-file store linking a login (email + bcrypt hash) to an existing
Customer ID.

This is *not* a pipeline artifact: it's created on first signup and lives at
``data/processed/auth_users.json`` (git-ignored). One account per email and one
account per Customer ID. The demo API is a single process, so a module-level
lock is enough to keep concurrent signups from corrupting the file.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_USERS_JSON = REPO_ROOT / "data" / "processed" / "auth_users.json"

_LOCK = threading.Lock()


def _read() -> dict[str, dict]:
    if not AUTH_USERS_JSON.exists():
        return {}
    with open(AUTH_USERS_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh).get("users", {})


def _write(users: dict[str, dict]) -> None:
    AUTH_USERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_USERS_JSON.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"users": users}, fh, indent=2, sort_keys=True)
    tmp.replace(AUTH_USERS_JSON)  # atomic on the same filesystem


def get_user(email: str) -> dict | None:
    """``{"customer_id": ..., "password_hash": ...}`` for this email, or None."""
    return _read().get(email.strip().lower())


def create_user(email: str, customer_id: str, password_hash: str) -> None:
    """Insert a new login. Raises ValueError if the email or Customer ID is
    already linked to an account (checked under the lock, so it's the
    authoritative uniqueness guard)."""
    email = email.strip().lower()
    with _LOCK:
        users = _read()
        if email in users:
            raise ValueError("email already registered")
        if any(u["customer_id"] == customer_id for u in users.values()):
            raise ValueError(
                f"customer_id '{customer_id}' is already linked to an account"
            )
        users[email] = {
            "customer_id": customer_id,
            "password_hash": password_hash,
        }
        _write(users)
