"""Stage 5 - SMS return reminders + health alerts.

Joins data/processed/stage1_output.csv with data/processed/customers.csv on
Customer ID. For every rental that is still checked out (Actual Check-In Date is
null) and whose Expected Return Date is exactly one "lead" away from TODAY, it
builds a reminder SMS and hands it to send_sms().

Connected Operators: run() and send_health_alerts() also notify any Contacts
linked to the asset (data/processed/assignments.csv) who opted into that alert
type, scoped to that one asset, and every send (customer + contact) is recorded
in data/processed/alert_log.csv. See the notify_demand note in
send_health_alerts() for why demand/reallocation insight is never sent here.

    lead = 3 days  if the customer's Risk Tier is "High"
    lead = 1 day   otherwise

Message:
    "Reminder: your <Type> (<Equipment ID>) is due back at <Site ID> tomorrow
     (<Expected Return Date>)."
(the "tomorrow" is replaced with "in 3 days" for the High-risk 3-day lead).

Nothing real is sent - send_sms() is a stub that prints. TODAY is a module
variable so tests can pin the clock; a real deployment would use date.today().

Run:
    python backend/stage5_customer_score/sms_alerts.py                # uses TODAY
    python backend/stage5_customer_score/sms_alerts.py 2025-05-18     # override

Useful test dates for this dataset:
    2025-11-23  -> High-tier 3-day reminder  (CUST01 / EQX1063, due 2025-11-26)
    2025-05-18  -> normal 1-day reminder     (CUST13 / EQX1006, due 2025-05-19)
    2025-01-14  -> normal 1-day reminder     (CUST08 / EQX1011, due 2025-01-15)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE1_OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage1_output.csv"
CUSTOMERS_CSV = REPO_ROOT / "data" / "processed" / "customers.csv"
_API_DIR = REPO_ROOT / "backend" / "api"


def _api_modules():
    """Lazy import of the API-layer stores (alert_log / contacts / data_access).

    Kept lazy so this module stays importable on its own and so there is no
    import cycle with data_access (which lazily imports this module in turn)."""
    if str(_API_DIR) not in sys.path:
        sys.path.insert(0, str(_API_DIR))
    import alert_log
    import contacts
    import data_access
    return alert_log, contacts, data_access


def _customer_phones() -> dict[str, str]:
    df = pd.read_csv(CUSTOMERS_CSV, dtype=str)
    return {
        str(r["Customer ID"]).strip(): (r.get("Phone Number") or "")
        for _, r in df.iterrows()
    }

# --- configurable clock for testing ---------------------------------------- #
TODAY = date(2025, 11, 23)

NORMAL_LEAD_DAYS = 1
HIGH_RISK_LEAD_DAYS = 3


# --------------------------------------------------------------------------- #
# SMS sink (stub)
# --------------------------------------------------------------------------- #
def send_sms(phone: str, message: str) -> None:
    """Pretend to send an SMS. Prints what would go out."""
    print(f"  [SMS -> {phone}]  {message}")
    # --- Real integration would go here, e.g. Twilio: --------------------- #
    #   from twilio.rest import Client
    #   client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    #   client.messages.create(
    #       to=phone, from_=TWILIO_FROM_NUMBER, body=message,
    #   )
    # -------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Reminder logic
# --------------------------------------------------------------------------- #
def lead_days_for_tier(risk_tier: object) -> int:
    return (HIGH_RISK_LEAD_DAYS
            if str(risk_tier).strip().lower() == "high"
            else NORMAL_LEAD_DAYS)


def _when_phrase(lead: int) -> str:
    return "tomorrow" if lead == 1 else f"in {lead} days"


def build_message(row: pd.Series) -> str:
    lead = int(row["lead_days"])
    exp = pd.to_datetime(row["Expected Return Date"]).date().isoformat()
    site = row["Site ID"] if pd.notna(row["Site ID"]) else "its site"
    return (
        f"Reminder: your {row['Type']} ({row['Equipment ID']}) is due back at "
        f"{site} {_when_phrase(lead)} ({exp})."
    )


def find_due_reminders(today: date | None = None) -> pd.DataFrame:
    """Still-checked-out rentals whose Expected Return Date is exactly `lead`
    days after `today` (lead depends on the customer's Risk Tier)."""
    today = today or TODAY
    s1 = pd.read_csv(STAGE1_OUTPUT_CSV,
                     parse_dates=["Expected Return Date", "Actual Check-In Date"])
    customers = pd.read_csv(CUSTOMERS_CSV, dtype=str)

    still_out = s1[s1["Actual Check-In Date"].isna()].merge(
        customers, on="Customer ID", how="left")
    still_out["lead_days"] = still_out["Risk Tier"].map(lead_days_for_tier)
    still_out["days_until_due"] = (
        still_out["Expected Return Date"].dt.normalize() - pd.Timestamp(today)
    ).dt.days

    return still_out[still_out["days_until_due"] == still_out["lead_days"]].copy()


def _notify_contacts(equipment_id: str, alert_type: str, message: str,
                     switch: str) -> int:
    """SMS + log every Contact linked to `equipment_id` whose `switch`
    (notify_due_date / notify_health) is on. Returns how many were notified.
    Safe to call when no assignments.csv exists yet (returns 0)."""
    alog, contacts, _ = _api_modules()
    n = 0
    for a in contacts.assignments_for_equipment(str(equipment_id)):
        if not a.get(switch):
            continue
        c = contacts.contact_by_id(a["contact_id"])
        if not c:
            continue
        send_sms(c["phone"], message)
        alog.append_alert_log(
            equipment_id=str(equipment_id), alert_type=alert_type,
            recipient_type="contact", recipient_id=c["contact_id"],
            phone=c["phone"], message=message, sent_successfully=True,
        )
        n += 1
    return n


def run(today: date | None = None) -> list[dict]:
    today = today or TODAY
    alog, _contacts, _da = _api_modules()
    s1 = pd.read_csv(STAGE1_OUTPUT_CSV, parse_dates=["Actual Check-In Date"])
    n_still_out = int(s1["Actual Check-In Date"].isna().sum())

    due = find_due_reminders(today).sort_values(
        ["lead_days", "Customer ID", "Equipment ID"])

    print(f"SMS reminder run  -  TODAY = {today.isoformat()}")
    print(f"still-checked-out rentals scanned : {n_still_out}")
    print(f"due for a reminder now            : {len(due)}\n")

    sent: list[dict] = []
    for _, row in due.iterrows():
        msg = build_message(row)
        send_sms(row["Phone Number"], msg)
        alog.append_alert_log(
            equipment_id=str(row["Equipment ID"]), alert_type="due_date",
            recipient_type="customer", recipient_id=str(row["Customer ID"]),
            phone=str(row["Phone Number"]), message=msg, sent_successfully=True,
        )
        n_contacts = _notify_contacts(
            row["Equipment ID"], "due_date", msg, "notify_due_date")
        if n_contacts:
            print(f"    +{n_contacts} connected contact(s)")
        sent.append({
            "customer_id": row["Customer ID"],
            "phone": row["Phone Number"],
            "risk_tier": row["Risk Tier"],
            "lead_days": int(row["lead_days"]),
            "equipment_id": row["Equipment ID"],
            "type": row["Type"],
            "site_id": row["Site ID"],
            "expected_return_date": pd.to_datetime(
                row["Expected Return Date"]).date().isoformat(),
            "message": msg,
        })

    # ---- summary --------------------------------------------------------- #
    n_high = sum(1 for s in sent if s["lead_days"] == HIGH_RISK_LEAD_DAYS)
    n_normal = len(sent) - n_high
    print("\n" + "-" * 70)
    print(f"{len(sent)} reminder(s) triggered  "
          f"({n_normal} normal 1-day, {n_high} high-risk 3-day)")
    for s in sent:
        tag = "HIGH/3d" if s["lead_days"] == HIGH_RISK_LEAD_DAYS else "1d"
        print(f"  {s['customer_id']}  {s['phone']:<15} {tag:<7} "
              f"{s['equipment_id']} {s['type']} @ {s['site_id']}  "
              f"due {s['expected_return_date']}")
    if not sent:
        print("  (nothing due at its lead time today)")
    return sent


def build_health_message(equipment_id: object, asset_type: object,
                         reasons: list) -> str:
    head = f"Health alert: {asset_type} ({equipment_id}) flagged by Stage 1"
    if reasons:
        head += f" - {reasons[0]}"
        if len(reasons) > 1:
            head += f" (+{len(reasons) - 1} more)"
    return head + "."


def send_health_alerts(today: date | None = None) -> list[dict]:
    """Dispatch health / idle alerts for every asset currently flagged by
    Stage 1.

    The account holder already sees these on their dashboard, so there is no
    SMS change for them - we just record it in the alert log. Any Contact
    linked to the asset with notify_health on gets the same one-line alert by
    SMS, scoped to that single asset. Every send is logged.

    notify_demand is a DELIBERATE NO-OP here. The switch exists in the
    Assignment data model for a future iteration, but demand_forecast /
    recommendation ("move this machine to site X") is account-holder-only
    decision information and must never reach a per-asset contact over this
    SMS path. So this function never reads or forwards demand/recommendation
    fields, regardless of any contact's notify_demand value.
    """
    today = today or TODAY  # not date-filtered today, but kept for a uniform API
    alog, contacts, da = _api_modules()

    flagged = da.latest_cycle_is_flagged()
    records = {str(r["equipment_id"]): r for r in da.load_pipeline_records()}
    phones = _customer_phones()

    sent: list[dict] = []
    for equipment_id, is_flagged in flagged.items():
        if not is_flagged:
            continue
        rec = records.get(str(equipment_id))
        if not rec:
            continue
        customer_id = str(rec.get("customer_id"))
        # reasons only - no demand_forecast / recommendation (see docstring)
        msg = build_health_message(
            equipment_id, rec.get("type"), rec.get("reasons") or [])

        alog.append_alert_log(
            equipment_id=str(equipment_id), alert_type="health",
            recipient_type="customer", recipient_id=customer_id,
            phone=phones.get(customer_id, ""), message=msg,
            sent_successfully=True,
        )
        sent.append({"equipment_id": str(equipment_id),
                     "recipient_type": "customer", "recipient_id": customer_id})

        n_contacts = _notify_contacts(
            equipment_id, "health", msg, "notify_health")
        for _ in range(n_contacts):
            sent.append({"equipment_id": str(equipment_id),
                         "recipient_type": "contact"})

    n_cust = sum(1 for s in sent if s["recipient_type"] == "customer")
    n_ct = sum(1 for s in sent if s["recipient_type"] == "contact")
    print(f"\nhealth alerts  -  {n_cust} flagged asset(s) logged to the "
          f"customer, {n_ct} connected-contact SMS")
    return sent


def _parse_today(argv: list[str]) -> date:
    if len(argv) > 1:
        return date.fromisoformat(argv[1])
    return TODAY


if __name__ == "__main__":
    _today = _parse_today(sys.argv)
    run(_today)
    send_health_alerts(_today)
