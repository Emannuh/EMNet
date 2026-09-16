"""
Session status router.
HTMX polls this endpoint to show remaining time / data on the splash page.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from captive_portal.core.security import decode_access_token
from captive_portal.core.tenant import get_tenant_schema

router = APIRouter()


class SessionStatus(BaseModel):
    active: bool
    minutes_remaining: int | None = None
    data_mb_remaining: int | None = None
    message: str


@router.get("/status", response_model=SessionStatus)
async def session_status(
    token: str,
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Returns the current session status for the given JWT.
    Used by the splash page for live status polling (HTMX).
    """
    payload = decode_access_token(token)
    # Placeholder — will query RADIUS accounting tables in next task
    return SessionStatus(
        active=True,
        minutes_remaining=55,
        message="Connected",
    )
