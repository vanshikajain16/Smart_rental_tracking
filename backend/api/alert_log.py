"""Persistent alert log - NEW in the Connected Operators feature.

Before this, Stage 5's SMS path only printed; nothing was recorded anywhere.
Every reminder / health alert that goes out (to a customer OR a linked contact)
is appended here.

Deliberately a leaf module: only stdlib, no project imports, so both the API
layer and the Stage 5 pipeline script can use it without import cycles.

data/processed/alert_log.csv columns:
    timestamp, equipment_id, alert_type, recipient_type, recipient_id,
    phone, message, sent_successfully
"""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERT_LOG_CSV = REPO_ROOT / "data" / "processed" / "alert_log.csv"

FIELDS = [
    "timestamp",
    "equipment_id",
    "alert_type",        # due_date | health
    "recipient_type",    # customer | contact
    "recipient_id",      # customer_id or contact_id
    "phone",
    "message",
    "sent_successfully",  # "True" / "False"
]

_lock = threading.Lock()


def append_alert_log(
    *,
    equipment_id: str,
    alert_type: str,
    recipient_type: str,
    recipient_id: str,
    phone: str | None,
    message: str,
    sent_successfully: bool = True,
) -> dict:
    """Append one row (creating the file with a header the first time)."""
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "equipment_id": equipment_id,
        "alert_type": alert_type,
        "recipient_type": recipient_type,
        "recipient_id": recipient_id,
        "phone": phone or "",
        "message": message,
        "sent_successfully": str(bool(sent_successfully)),
    }
    with _lock:
        is_new = not ALERT_LOG_CSV.exists()
        ALERT_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_LOG_CSV, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    return row


def read_alert_log(equipment_id: str | None = None) -> list[dict]:
    """All log rows, newest first; optionally filtered to one equipment_id."""
    if not ALERT_LOG_CSV.exists():
        return []
    with open(ALERT_LOG_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if equipment_id is not None:
        rows = [r for r in rows if r.get("equipment_id") == equipment_id]
    rows.reverse()
    return rows
