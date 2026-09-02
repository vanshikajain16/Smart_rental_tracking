"""Customer authentication - hashing, JWT, account store, and the /auth routes.

Everything auth-related lives in this one module:

* a passlib bcrypt ``CryptContext`` for hashing / verifying passwords
* ``create_access_token`` / ``decode_access_token`` (python-jose, HS256)
* a CSV-backed account store at ``data/processed/customer_accounts.csv``
* the ``auth_router`` with ``POST /auth/signup`` and ``POST /auth/login``
* ``get_current_customer`` - a FastAPI dependency other routers use to read the
  caller's Customer ID out of the bearer token.

Signup only ever links a login to a Customer ID that already exists in
``data/processed/customers.csv`` - the pipeline is scoped to ids that already
have rental history.
"""
from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

import data_access as da

# --------------------------------------------------------------------------- #
# 1. Password hashing
# --------------------------------------------------------------------------- #
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        # malformed hash on disk - treat as a failed verification, not a 500
        return False


# --------------------------------------------------------------------------- #
# 2. JWT helpers
# --------------------------------------------------------------------------- #
# SECURITY: this fallback exists ONLY so the project runs locally with zero
# setup. It is public and therefore worthless as a signing secret. Any real
# deployment MUST set SECRET_KEY via the RENTAL_JWT_SECRET environment variable.
SECRET_KEY = os.environ.get(
    "RENTAL_JWT_SECRET", "insecure-local-dev-only-key-change-me"
)
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(customer_id: str, expires_minutes: int = 60) -> str:
    """Sign a JWT whose ``sub`` claim is the Customer ID."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": customer_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the ``sub`` (customer_id) claim of a valid token.

    Raises ``jose.JWTError`` if the token is malformed, tampered with, or
    expired, and ``ValueError`` if it carries no subject.
    """
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    customer_id = payload.get("sub")
    if not customer_id:
        raise ValueError("token is missing its subject claim")
    return customer_id


# --------------------------------------------------------------------------- #
# 3. Account store  (data/processed/customer_accounts.csv)
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS_CSV = REPO_ROOT / "data" / "processed" / "customer_accounts.csv"
ACCOUNT_FIELDS = ["email", "hashed_password", "customer_id", "created_at"]

_accounts_lock = threading.Lock()


def _ensure_accounts_file() -> None:
    """Create the CSV with just a header row if it doesn't exist yet."""
    if ACCOUNTS_CSV.exists():
        return
    ACCOUNTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_CSV, "w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=ACCOUNT_FIELDS).writeheader()


def read_accounts() -> list[dict]:
    """Every account row (empty list when the store is brand new)."""
    _ensure_accounts_file()
    with open(ACCOUNTS_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def find_account_by_email(email: str) -> dict | None:
    email = email.strip().lower()
    for row in read_accounts():
        if row.get("email", "").strip().lower() == email:
            return row
    return None


def account_exists_for_customer(customer_id: str) -> bool:
    return any(row.get("customer_id") == customer_id for row in read_accounts())


def append_account(email: str, hashed_password: str, customer_id: str) -> dict:
    """Append one account row. Re-checks email / customer_id uniqueness while
    holding the lock, so it stays correct even if two signups race past the
    endpoint's friendlier pre-checks. Raises ValueError on a duplicate."""
    email = email.strip().lower()
    row = {
        "email": email,
        "hashed_password": hashed_password,
        "customer_id": customer_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _accounts_lock:
        existing = read_accounts()
        if any(r.get("email", "").strip().lower() == email for r in existing):
            raise ValueError("email already registered")
        if any(r.get("customer_id") == customer_id for r in existing):
            raise ValueError("customer_id already linked to an account")
        with open(ACCOUNTS_CSV, "a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=ACCOUNT_FIELDS).writerow(row)
    return row


# --------------------------------------------------------------------------- #
# 4/5. Routes
# --------------------------------------------------------------------------- #
auth_router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


class SignupBody(BaseModel):
    email: str
    password: str
    customer_id: str


class LoginBody(BaseModel):
    email: str
    password: str


@auth_router.post("/signup")
def signup(body: SignupBody):
    email = body.email.strip().lower()
    customer_id = body.customer_id.strip()

    if customer_id not in da.customer_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"customer_id '{customer_id}' is not a known customer - "
                "signups can only be linked to a Customer ID that already has "
                "rental history"
            ),
        )
    if find_account_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account already exists for this email",
        )
    if account_exists_for_customer(customer_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this customer_id is already linked to an account",
        )

    try:
        append_account(email, hash_password(body.password), customer_id)
    except ValueError as exc:  # lost a race on one of the checks above
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )

    return {"message": "account created"}


@auth_router.get("/check-email")
def check_email(email: str):
    """Whether an email is already registered - a client-side UX hint only.

    Safe to expose: it never touches passwords, so ``/auth/login`` can stay
    deliberately non-committal about which half of the pair was wrong. Do not
    build security logic on this.
    """
    return {"exists": find_account_by_email(email) is not None}


@auth_router.post("/login")
def login(body: LoginBody):
    account = find_account_by_email(body.email)
    if account is None or not verify_password(
        body.password, account["hashed_password"]
    ):
        raise _INVALID_CREDENTIALS
    token = create_access_token(account["customer_id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "customer_id": account["customer_id"],
    }


# --------------------------------------------------------------------------- #
# 6. Dependency
# --------------------------------------------------------------------------- #
def get_current_customer(token: str = Depends(oauth2_scheme)) -> str:
    """The Customer ID carried by a valid bearer token.

    ``OAuth2PasswordBearer`` already answers 401 when the Authorization header
    is missing; this turns a malformed / expired / subject-less token into the
    same 401.
    """
    try:
        return decode_access_token(token)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
