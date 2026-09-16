"""
Voucher redemption router.
After payment succeeds, the end-user submits the voucher code
(or it's auto-redeemed); we create the RADIUS account and return
a short-lived session token.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from captive_portal.core.tenant import get_tenant_schema
from captive_portal.core.security import create_access_token

router = APIRouter()


class RedeemRequest(BaseModel):
    voucher_code: str
    mac_address: str
    client_ip: str


class RedeemResponse(BaseModel):
    access_token: str
    expires_in_minutes: int
    message: str


@router.post("/redeem", response_model=RedeemResponse)
async def redeem_voucher(
    payload: RedeemRequest,
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Validates a voucher, creates the RADIUS credentials,
    and returns a session token.
    Full RADIUS integration implemented in the radius task.
    """
    # Placeholder — real lookup + RADIUS account creation in next task
    if not payload.voucher_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Voucher code required")

    token = create_access_token(subject=f"{tenant_schema}:{payload.voucher_code}")
    return RedeemResponse(
        access_token=token,
        expires_in_minutes=60,
        message="Voucher redeemed. You are now connected.",
    )
