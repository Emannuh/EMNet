"""
Payments router — M-Pesa STK Push initiation and callback.

STK Push flow:
  1. Validate phone + plan
  2. Look up plan in tenant schema to get the price
  3. Create a pending Payment record in the tenant schema
  4. Call Daraja STK Push via apps.billing.mpesa (Django app — called via
     subprocess since the portal is FastAPI, not Django)
  5. Store the checkout_request_id so the callback can match it back

Callback flow:
  1. Daraja POSTs to /payments/callback
  2. Parse and validate the payload
  3. Dispatch a Celery task to process the result (create voucher on success)

NOTE ON ARCHITECTURE:
  The captive portal (FastAPI) calls M-Pesa by importing the Django
  billing.mpesa module directly. This works because both services run
  in the same container image and share the same Python path.
  The callback dispatches a Celery task so the heavy work (DB writes,
  RADIUS provisioning) happens asynchronously and the response to
  Daraja is immediate (Safaricom requires a quick response).
"""
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from captive_portal.core.tenant import get_tenant_schema
from captive_portal.core.database import get_tenant_conn
from captive_portal.core.limiter import limiter
from captive_portal.core.mpesa import (
    stk_push, parse_callback,
    MpesaNotConfigured, MpesaApiError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class StkPushRequest(BaseModel):
    phone_number: str = Field(
        ...,
        pattern=r"^2547\d{8}$",
        description="Safaricom number in 2547XXXXXXXX format",
    )
    plan_id: int = Field(..., gt=0)
    mac_address: str = Field(..., description="Client device MAC")


class StkPushResponse(BaseModel):
    checkout_request_id: str
    message: str


# ── STK Push ──────────────────────────────────────────────────────────────────

@router.post("/stk-push", response_model=StkPushResponse)
@limiter.limit("5/minute")
async def initiate_stk_push(
    request: Request,
    payload: StkPushRequest,
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Initiates M-Pesa STK Push for the requested voucher plan.

    Returns:
      200  checkout_request_id from Daraja (or local ref if creds missing)
      404  plan not found or inactive
      503  Daraja API unavailable
    """
    # 1. Look up the plan in the tenant schema
    try:
        async with get_tenant_conn(tenant_schema) as conn:
            plan = await conn.fetchrow(
                "SELECT id, name, price_kes FROM portal_voucherplan "
                "WHERE id=$1 AND is_active=true",
                payload.plan_id,
            )
    except Exception as exc:
        logger.exception("DB error looking up plan %d in %s", payload.plan_id, tenant_schema)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable. Please try again.",
        )

    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {payload.plan_id} not found or inactive.",
        )

    amount = int(float(plan["price_kes"]))
    plan_name = plan["name"]

    # 2. Create a pending Payment record and get a reference UUID
    import uuid as _uuid
    reference = str(_uuid.uuid4())
    try:
        async with get_tenant_conn(tenant_schema) as conn:
            await conn.execute(
                """
                INSERT INTO billing_payment
                    (reference, phone_number, amount_kes, status, failure_reason,
                     mpesa_checkout_request_id, mpesa_receipt_number,
                     created_at, updated_at)
                VALUES ($1,$2,$3,'pending','',$4,'',now(),now())
                """,
                reference,
                payload.phone_number,
                str(amount),
                "",  # checkout_request_id filled in after STK push
            )
    except Exception as exc:
        logger.exception("Failed to create Payment record in %s", tenant_schema)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not record payment. Please try again.",
        )

    # 3. Call Daraja STK Push
    try:
        result = stk_push(
            phone=payload.phone_number,
            amount=amount,
            account_ref=reference[:12].upper(),
            description=f"{plan_name[:13]}",
            callback_path="/payments/callback",
        )
        checkout_request_id = result["CheckoutRequestID"]

    except MpesaNotConfigured as exc:
        logger.error("M-Pesa not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Payment service is not configured. "
                "Please contact the ISP administrator."
            ),
        )
    except MpesaApiError as exc:
        logger.error("Daraja error for plan %s: %s", plan_name, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway error. Please try again in a moment.",
        )

    # 4. Update the payment record with the checkout_request_id
    try:
        async with get_tenant_conn(tenant_schema) as conn:
            await conn.execute(
                "UPDATE billing_payment SET mpesa_checkout_request_id=$1, updated_at=now() "
                "WHERE reference=$2",
                checkout_request_id,
                reference,
            )
    except Exception as exc:
        logger.error("Could not update checkout_request_id for payment %s: %s", reference, exc)
        # Not fatal — the callback will still work if it arrives

    logger.info(
        "STK Push initiated: tenant=%s phone=%s plan=%s amount=%s checkout_id=%s",
        tenant_schema, payload.phone_number, plan_name, amount, checkout_request_id,
    )

    return StkPushResponse(
        checkout_request_id=checkout_request_id,
        message=f"Payment request of KES {amount} sent to {payload.phone_number}. "
                f"Enter your M-Pesa PIN to complete.",
    )


# ── Callback ──────────────────────────────────────────────────────────────────

@router.post("/callback")
async def mpesa_callback(request: Request):
    """
    Receives the async result callback from Safaricom Daraja.
    Must respond quickly — heavy work dispatched via Celery.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    try:
        parsed = parse_callback(body)
    except (KeyError, ValueError) as exc:
        logger.error("Malformed M-Pesa callback: %s body=%s", exc, body)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed payload")

    checkout_request_id = parsed["checkout_request_id"]
    result_code         = parsed["result_code"]
    receipt             = parsed.get("receipt_number") or ""
    phone               = parsed.get("phone_number") or ""
    amount              = parsed.get("amount") or 0

    logger.info(
        "M-Pesa callback: checkout_id=%s result_code=%s receipt=%s",
        checkout_request_id, result_code, receipt,
    )

    # Find which tenant owns this checkout_request_id and dispatch the task
    tenant_schema = await _find_tenant_for_checkout_id(checkout_request_id)

    if tenant_schema:
        # Dispatch Celery task — it will handle voucher creation or invoice payment
        try:
            # Use the Celery app directly — no Django setup needed
            from config.celery import app as celery_app
            celery_app.send_task(
                "portal.process_voucher_payment_callback",
                kwargs=dict(
                    schema_name=tenant_schema,
                    checkout_request_id=checkout_request_id,
                    result_code=result_code,
                    receipt_number=receipt,
                    phone_number=phone,
                    amount=amount,
                ),
            )
            logger.info(
                "Dispatched voucher callback task for tenant=%s checkout=%s",
                tenant_schema, checkout_request_id,
            )
        except Exception as exc:
            logger.error("Failed to dispatch callback Celery task: %s", exc)
    else:
        # Try subscriber invoice path
        inv_schema = await _find_invoice_tenant_for_checkout_id(checkout_request_id)
        if inv_schema:
            try:
                from config.celery import app as celery_app
                celery_app.send_task(
                    "subscribers.process_invoice_payment_callback",
                    kwargs=dict(
                        schema_name=inv_schema,
                        checkout_request_id=checkout_request_id,
                        result_code=result_code,
                        receipt_number=receipt,
                        failure_reason="" if result_code == 0 else parsed.get("result_desc", ""),
                    ),
                )
            except Exception as exc:
                logger.error("Failed to dispatch invoice callback task: %s", exc)
        else:
            logger.warning(
                "No tenant found for checkout_request_id=%s — callback dropped",
                checkout_request_id,
            )

    # Always return success to Daraja
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _find_tenant_for_checkout_id(checkout_request_id: str):
    """
    Search billing_payment across all tenant schemas for a matching
    checkout_request_id. Returns the schema_name or None.
    """
    try:
        async with get_tenant_conn("public") as conn:
            rows = await conn.fetch(
                "SELECT schema_name FROM tenants_tenant "
                "WHERE schema_name != 'public' AND is_active = true"
            )
    except Exception as exc:
        logger.error("Could not fetch tenant list: %s", exc)
        return None

    for row in rows:
        schema = row["schema_name"]
        try:
            async with get_tenant_conn(schema) as conn:
                r = await conn.fetchrow(
                    "SELECT reference FROM billing_payment "
                    "WHERE mpesa_checkout_request_id=$1 LIMIT 1",
                    checkout_request_id,
                )
                if r:
                    return schema
        except Exception:
            continue
    return None


async def _find_invoice_tenant_for_checkout_id(checkout_request_id: str):
    """Find the tenant that owns a subscribers_invoicepayment with this checkout_id."""
    try:
        async with get_tenant_conn("public") as conn:
            rows = await conn.fetch(
                "SELECT schema_name FROM tenants_tenant "
                "WHERE schema_name != 'public' AND is_active = true"
            )
    except Exception as exc:
        logger.error("Could not fetch tenant list for invoice lookup: %s", exc)
        return None

    for row in rows:
        schema = row["schema_name"]
        try:
            async with get_tenant_conn(schema) as conn:
                r = await conn.fetchrow(
                    "SELECT id FROM subscribers_invoicepayment "
                    "WHERE mpesa_checkout_request_id=$1 LIMIT 1",
                    checkout_request_id,
                )
                if r:
                    return schema
        except Exception:
            continue
    return None
