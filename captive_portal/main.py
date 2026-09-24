"""
Emmsuite ISP — Captive Portal FastAPI Service
=============================================
Public-facing, high-traffic service that handles:
  1. Splash page delivery (redirect URL from NAS/router)
  2. M-Pesa STK Push initiation
  3. M-Pesa payment callback
  4. Voucher redemption → RADIUS account creation
  5. Session status polling (HTMX-friendly JSON endpoint)

Tenancy: the tenant (ISP) is identified by subdomain/Host header,
passed as X-Tenant-Schema header from the reverse proxy, or derived
from the request hostname.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from captive_portal.core.config import settings
from captive_portal.core.limiter import limiter
from captive_portal.routers import splash, payments, vouchers, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    yield


app = FastAPI(
    title="Emmsuite ISP Captive Portal",
    description="Voucher purchase, redemption, and WiFi session management.",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Attach rate limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(splash.router,    prefix="/portal",   tags=["Splash"])
app.include_router(payments.router,  prefix="/payments", tags=["Payments"])
app.include_router(vouchers.router,  prefix="/vouchers", tags=["Vouchers"])
app.include_router(sessions.router,  prefix="/sessions", tags=["Sessions"])


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe used by Docker / load balancer."""
    return {"status": "ok"}
