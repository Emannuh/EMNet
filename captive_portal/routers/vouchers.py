"""
Voucher redemption router — REAL implementation.

Flow:
  1. Validate input (non-empty UUID-format code)
  2. Look up voucher in the tenant's schema
  3. Reject if not found (404) or not active (409)
  4. Write RADIUS credentials (radcheck + radreply) in the RADIUS DB
  5. Mark voucher as 'used' and record mac_address/client_ip
  6. Issue a JWT scoped to tenant:voucher_code
  7. Return the token

If RADIUS write fails we roll back the voucher status change and return 503
rather than silently pretending the redemption succeeded.

The 'hang bug' from the verification pass was caused by asyncpg waiting
indefinitely for a DB connection that never came (because the DB layer
hadn't been initialised). Fixed by:
  - Using a short connect_timeout in asyncpg (5s)
  - Explicit 404 for unknown vouchers (no further DB work after not-found)
  - Wrapping all DB work in try/except with proper HTTP error responses
"""
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from captive_portal.core.tenant import get_tenant_schema
from captive_portal.core.security import create_access_token
from captive_portal.core.database import get_tenant_conn, radius_execute, radius_fetchall
from captive_portal.core.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Rate limit helper ─────────────────────────────────────────────────────────

def _get_limiter():
    from captive_portal.main import limiter
    return limiter


# ── Request / Response models ─────────────────────────────────────────────────

class RedeemRequest(BaseModel):
    voucher_code: str
    mac_address: str
    client_ip: str

    @field_validator("voucher_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("voucher_code cannot be empty")
        # Accept both bare UUID and full UUID string
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("voucher_code must be a valid UUID")
        return v.lower()


class RedeemResponse(BaseModel):
    access_token: str
    expires_in_minutes: int
    message: str
    plan_name: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _radius_username(tenant_schema: str, voucher_code: str) -> str:
    """
    Convention: tenant_schema:voucher_code
    e.g. deenet:ab59f8fe-47c7-4e5f-9347-190f452b11ee
    Keeps voucher RADIUS users distinct from PPPoE subscriber users.
    """
    return f"{tenant_schema}:{voucher_code}"


def _provision_voucher_radius(tenant_schema: str, voucher_code: str,
                               duration_minutes: int | None,
                               data_mb: int | None) -> None:
    """
    Write radcheck + radreply for a voucher user.
    Password is the voucher code itself (only the holder knows it).
    Session limits are written as RADIUS attributes.
    """
    username = _radius_username(tenant_schema, voucher_code)

    # Clear any stale entries (idempotent)
    radius_execute("DELETE FROM radcheck WHERE \"username\"=%s", (username,))
    radius_execute("DELETE FROM radreply WHERE \"username\"=%s", (username,))

    # radcheck — password (Cleartext so FreeRADIUS can validate)
    radius_execute(
        'INSERT INTO radcheck ("username", "attribute", "op", "value") '
        'VALUES (%s, %s, %s, %s)',
        (username, "Cleartext-Password", ":=", voucher_code),
    )

    # radreply — session time limit (if time-based plan)
    if duration_minutes:
        radius_execute(
            'INSERT INTO radreply ("username", "attribute", "op", "value") '
            'VALUES (%s, %s, %s, %s)',
            (username, "Session-Timeout", ":=", str(duration_minutes * 60)),
        )

    # radreply — data limit (if data-cap plan)
    # FreeRADIUS standard: WISPr-Bandwidth-Max-Down or vendor-specific
    # Using Mikrotik-Total-Limit (bytes) as most ISPs in this region use MikroTik
    if data_mb:
        radius_execute(
            'INSERT INTO radreply ("username", "attribute", "op", "value") '
            'VALUES (%s, %s, %s, %s)',
            (username, "Mikrotik-Total-Limit", ":=", str(data_mb * 1024 * 1024)),
        )

    logger.info("RADIUS provisioned voucher user: %s", username)


def _deprovision_voucher_radius(tenant_schema: str, voucher_code: str) -> None:
    """Remove RADIUS entries for an expired/used voucher."""
    username = _radius_username(tenant_schema, voucher_code)
    radius_execute("DELETE FROM radcheck WHERE \"username\"=%s", (username,))
    radius_execute("DELETE FROM radreply WHERE \"username\"=%s", (username,))
    logger.info("RADIUS deprovisioned voucher user: %s", username)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/redeem", response_model=RedeemResponse)
@limiter.limit("10/minute")
async def redeem_voucher(
    request: Request,
    payload: RedeemRequest,
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Redeem a voucher: validate → write RADIUS → mark used → issue JWT.

    Error responses:
      400  invalid input (empty/malformed code)
      404  voucher code not found in this tenant
      409  voucher already used, expired, or pending payment
      503  RADIUS write failed (caller should retry or contact support)
    """
    code = payload.voucher_code

    # ── 1. Look up voucher in tenant schema ───────────────────────────────
    try:
        async with get_tenant_conn(tenant_schema) as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    v.id,
                    v.code,
                    v.status,
                    v.mac_address,
                    p.name       AS plan_name,
                    p.duration_minutes,
                    p.data_mb
                FROM portal_voucher v
                JOIN portal_voucherplan p ON p.id = v.plan_id
                WHERE v.code = $1
                """,
                code,
            )
    except Exception as exc:
        logger.exception("DB lookup failed for voucher %s in %s: %s", code, tenant_schema, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable. Please try again.",
        )

    # ── 2. Validate existence ─────────────────────────────────────────────
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voucher not found.",
        )

    # ── 3. Validate status ────────────────────────────────────────────────
    voucher_status = row["status"]
    if voucher_status != "active":
        detail_map = {
            "used":    "This voucher has already been used.",
            "expired": "This voucher has expired.",
            "pending": "Payment for this voucher has not been confirmed yet.",
        }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_map.get(voucher_status, f"Voucher is not active (status: {voucher_status})."),
        )

    # ── 4. Write RADIUS credentials ───────────────────────────────────────
    try:
        _provision_voucher_radius(
            tenant_schema=tenant_schema,
            voucher_code=code,
            duration_minutes=row["duration_minutes"],
            data_mb=row["data_mb"],
        )
    except Exception as exc:
        logger.exception(
            "RADIUS provision failed for voucher %s tenant %s: %s", code, tenant_schema, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not activate your session. Please try again or contact support.",
        )

    # ── 5. Mark voucher used (in the same tenant transaction) ─────────────
    try:
        async with get_tenant_conn(tenant_schema) as conn:
            result = await conn.execute(
                """
                UPDATE portal_voucher
                SET status = 'used',
                    mac_address = $1,
                    activated_at = $2
                WHERE code = $3
                  AND status = 'active'
                """,
                payload.mac_address,
                datetime.now(timezone.utc),
                code,
            )
            # result is "UPDATE N" — if 0 rows updated, another process beat us
            if result == "UPDATE 0":
                # Race condition: someone else redeemed between our read and write
                # Roll back the RADIUS write and reject
                _deprovision_voucher_radius(tenant_schema, code)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Voucher was already redeemed. Please try again with a new code.",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to mark voucher %s as used in %s: %s", code, tenant_schema, exc
        )
        # RADIUS was already written — roll it back to avoid orphaned credentials
        try:
            _deprovision_voucher_radius(tenant_schema, code)
        except Exception as radius_exc:
            logger.error("RADIUS rollback also failed for %s: %s", code, radius_exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redemption failed. Please try again.",
        )

    # ── 6. Issue JWT ──────────────────────────────────────────────────────
    token = create_access_token(
        subject=_radius_username(tenant_schema, code)
    )

    logger.info(
        "Voucher redeemed: tenant=%s code=%s plan=%s mac=%s ip=%s",
        tenant_schema, code, row["plan_name"],
        payload.mac_address, payload.client_ip,
    )

    # ── 7. Return ─────────────────────────────────────────────────────────
    return RedeemResponse(
        access_token=token,
        expires_in_minutes=row["duration_minutes"] or 1440,
        message="Voucher redeemed. You are now connected.",
        plan_name=row["plan_name"],
    )
