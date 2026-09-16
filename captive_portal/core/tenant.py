"""
Tenant resolution for the captive portal service.
The reverse proxy (nginx/Traefik) adds X-Tenant-Schema header,
which maps to the Postgres schema for that ISP.
"""
from fastapi import Header, HTTPException, status


async def get_tenant_schema(x_tenant_schema: str = Header(...)) -> str:
    """
    Dependency: extracts and validates the tenant schema name from the
    X-Tenant-Schema request header set by the reverse proxy.
    """
    schema = x_tenant_schema.strip().lower()
    if not schema or not schema.replace("_", "").isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing X-Tenant-Schema header",
        )
    return schema
