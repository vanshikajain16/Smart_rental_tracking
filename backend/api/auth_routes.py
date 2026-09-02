"""Customer authentication endpoints.

POST /auth/signup  - link a new login (email + password) to an EXISTING
                     Customer ID from customers.csv. Unknown ids are rejected
                     (the pipeline is scoped to ids that already have rental
                     history); an already-claimed id or email is a conflict.
                     Returns a bearer token.
POST /auth/login   - exchange email + password for a bearer token.
GET  /auth/me      - the Customer ID + email behind the presented token.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

import auth
import auth_store
import data_access as da
from schemas import AuthedCustomer, LoginRequest, SignupRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid email or password",
)


@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(body: SignupRequest):
    if body.customer_id not in da.customer_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"customer_id '{body.customer_id}' is not a known customer - "
                "signups can only be linked to a Customer ID that already has "
                "rental history"
            ),
        )
    try:
        auth_store.create_user(
            email=body.email,
            customer_id=body.customer_id,
            password_hash=auth.hash_password(body.password),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    token = auth.create_access_token(body.customer_id, body.email)
    return TokenResponse(access_token=token, customer_id=body.customer_id)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = auth_store.get_user(body.email)
    if user is None or not auth.verify_password(
        body.password, user["password_hash"]
    ):
        raise _INVALID_LOGIN
    token = auth.create_access_token(user["customer_id"], body.email)
    return TokenResponse(access_token=token, customer_id=user["customer_id"])


@router.get("/me", response_model=AuthedCustomer)
def me(claims: dict = Depends(auth.current_token_claims)):
    return AuthedCustomer(
        customer_id=claims["sub"], email=claims.get("email", "")
    )
