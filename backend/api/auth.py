"""Customer authentication: password hashing + JWT.

passlib (bcrypt scheme) hashes passwords; python-jose mints and verifies the
signed tokens. A token's ``sub`` claim is the linked Customer ID - protected
customer routes read it via ``current_customer_id`` and refuse to serve a
different id.

The signing secret comes from ``RENTAL_JWT_SECRET`` with a dev-only fallback so
the demo runs with zero setup. Set a real secret in any deployment.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.environ.get(
    "RENTAL_JWT_SECRET", "dev-only-insecure-secret-change-me"
)
JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = dict(
    status_code=status.HTTP_401_UNAUTHORIZED,
    headers={"WWW-Authenticate": "Bearer"},
)


def hash_password(plain: str) -> str:
    return _PWD.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _PWD.verify(plain, hashed)
    except ValueError:
        # malformed hash on disk - treat as a failed login, not a 500
        return False


def create_access_token(customer_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": customer_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def current_token_claims(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Decoded payload of a valid Bearer token, or 401."""
    if creds is None or not creds.credentials:
        raise HTTPException(detail="missing bearer token", **_UNAUTHORIZED)
    try:
        claims = jwt.decode(
            creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
    except JWTError:
        raise HTTPException(detail="invalid or expired token", **_UNAUTHORIZED)
    if not claims.get("sub"):
        raise HTTPException(detail="token has no subject", **_UNAUTHORIZED)
    return claims


def current_customer_id(
    claims: dict = Depends(current_token_claims),
) -> str:
    """The Customer ID carried by a valid Bearer token."""
    return claims["sub"]
