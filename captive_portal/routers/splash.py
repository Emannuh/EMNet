"""
Splash page router.
The NAS/router redirects unauthenticated clients here.
We return the HTML splash page (or JSON for HTMX partial updates).
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from captive_portal.core.tenant import get_tenant_schema

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def splash_page(
    mac: str = Query("", description="Client MAC address passed by NAS"),
    ip: str = Query("", description="Client IP address passed by NAS"),
    url: str = Query("", description="Original URL the client was trying to reach"),
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Entry point for captive portal redirection.
    Returns the splash/voucher-purchase HTML page.
    Full template rendering will be added in the next task.
    """
    return HTMLResponse(
        content=f"""
        <html><body>
        <h1>Welcome to the WiFi Portal</h1>
        <p>Tenant: {tenant_schema} | MAC: {mac} | IP: {ip}</p>
        <p>Voucher purchase form will appear here.</p>
        </body></html>
        """
    )
