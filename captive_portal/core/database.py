"""
Async database access for the captive portal service.

Two connections:
  - tenant_db  : asyncpg connection to the main netsuite_isp Postgres DB,
                 schema-switched per request to the tenant's schema.
  - radius_db  : synchronous psycopg2 connection to the FreeRADIUS
                 `radius` database (same pattern as Django's radius_service.py).

We keep the RADIUS connection synchronous because:
  1. psycopg2 has no async driver that works cleanly with asyncpg's event loop
  2. RADIUS writes are fast (single INSERT/DELETE) and rare (one per redemption)
  3. It keeps the RADIUS layer identical to Django's implementation

Usage (in a route):
    async with get_tenant_conn(schema) as conn:
        row = await conn.fetchrow("SELECT * FROM portal_voucher WHERE code=$1", code)

    with get_radius_conn() as conn:
        conn.cursor().execute("INSERT INTO radcheck ...")
"""

import asyncpg
import psycopg2
import psycopg2.extras
from contextlib import asynccontextmanager, contextmanager

from .config import settings


# ── Tenant DB (async) ─────────────────────────────────────────────────────────

@asynccontextmanager
async def get_tenant_conn(schema: str):
    """
    Opens a single asyncpg connection, sets search_path to the tenant schema,
    then cleans up on exit. Not pooled — portal is stateless and connections
    are short-lived. Pool can be added later if load demands it.
    """
    conn = await asyncpg.connect(settings.async_database_url, timeout=5.0)
    try:
        # Validate schema name to prevent injection (alphanumeric + underscore only)
        if not schema.replace("_", "").isalnum():
            raise ValueError(f"Invalid schema name: {schema!r}")
        await conn.execute(f'SET search_path TO "{schema}", public')
        yield conn
    finally:
        await conn.close()


# ── RADIUS DB (sync) ──────────────────────────────────────────────────────────

def _radius_dsn() -> str:
    return (
        f"host={settings.postgres_host} "
        f"port={settings.postgres_port} "
        f"dbname=radius "
        f"user={settings.radius_db_user} "
        f"password={settings.radius_db_password} "
        f"connect_timeout=5"
    )


@contextmanager
def get_radius_conn():
    """
    Opens a short-lived psycopg2 connection to the FreeRADIUS database.
    Commits on success, rolls back on exception, always closes.
    """
    conn = psycopg2.connect(_radius_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def radius_execute(sql: str, params: tuple = ()) -> None:
    """Execute a single parameterised statement against the RADIUS DB."""
    with get_radius_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def radius_fetchall(sql: str, params: tuple = ()) -> list:
    """Fetch all rows from the RADIUS DB."""
    with get_radius_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
