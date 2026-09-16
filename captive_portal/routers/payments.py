"""
Payments router — M-Pesa STK Push initiation and callback.
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from captive_portal.core.tenant import get_tenant_schema

router = APIRouter()


class StkPushRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^2547\d{8}$", description="Safaricom number in 2547XXXXXXXX format")
    plan_id: int = Field(..., gt=0)
    mac_address: str = Field(..., description="Client device MAC")


class StkPushResponse(BaseModel):
    checkout_request_id: str
    message: str


class MpesaCallback(BaseModel):
    """Raw M-Pesa Daraja callback payload (simplified)."""
    Body: dict


@router.post("/stk-push", response_model=StkPushResponse)
async def initiate_stk_push(
    payload: StkPushRequest,
    background_tasks: BackgroundTasks,
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Initiates M-Pesa STK Push for the requested voucher plan.
    Full M-Pesa Daraja integration implemented in billing task.
    """
    # Placeholder — will call MpesaService in billing task
    return StkPushResponse(
        checkout_request_id="PLACEHOLDER_CHECKOUT_ID",
        message="Payment request sent to your phone.",
    )


@router.post("/callback")
async def mpesa_callback(
    payload: MpesaCallback,
    background_tasks: BackgroundTasks,
):
    """
    Receives the async result callback from Safaricom Daraja.
    No tenant header needed — Daraja posts to a fixed URL;
    tenant is resolved from the stored checkout_request_id.
    """
    # Placeholder — will process callback and activate voucher
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
