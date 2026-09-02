"""Smart Rental Tracking API.

    python backend/api/main.py            # serve on http://127.0.0.1:8000
    #  docs at /docs

Serves the dual dashboard's data from the real pipeline outputs. If an expected
artifact is missing the API answers 503 with the command that regenerates it.
"""
from __future__ import annotations

import sys
from pathlib import Path

# so `import data_access` / `customer_routes` work when run as a plain script
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

import data_access as da  # noqa: E402
from auth_routes import router as auth_router  # noqa: E402
from customer_routes import router as customer_router  # noqa: E402
from dealer_routes import router as dealer_router  # noqa: E402

app = FastAPI(
    title="Smart Rental Tracking API",
    version="0.1.0",
    description="Customer + dealer views over the Stage 1-5 pipeline outputs.",
)

# Local dev: the Vite dev server (5173) calls this API on 8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(customer_router)
app.include_router(dealer_router)


@app.exception_handler(FileNotFoundError)
async def _missing_artifact(request: Request, exc: FileNotFoundError):
    return JSONResponse(
        status_code=503,
        content={"detail": f"pipeline artifact missing: {exc}"},
    )


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "smart-rental-tracking",
        "endpoints": [
            "/auth/signup",
            "/auth/login",
            "/auth/me",
            "/customer/{customer_id}/assets",
            "/customer/{customer_id}/alerts",
            "/customer/{customer_id}/sms-reminders",
            "/dealer/customers",
            "/dealer/renewal-risk",
            "/config/asset-types",
            "/docs",
        ],
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/config/asset-types", tags=["meta"])
def asset_types():
    """Per-Type config incl. custom_fields, straight from
    data/raw/asset_type_config.json. The frontend uses custom_fields to render
    type-specific fields dynamically."""
    return da.asset_type_config()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
