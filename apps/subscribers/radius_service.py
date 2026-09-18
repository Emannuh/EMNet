"""
RADIUS service layer for subscriber management.

Handles writing/removing credentials in the FreeRADIUS SQL tables
(radcheck, radreply, radusergroup) that live in the RADIUS database.

Architecture note
-----------------
FreeRADIUS uses its own `radius` database (not the tenant schema).
We connect to it directly using the RADIUS_DB_* env vars that are
already defined in .env.  All functions in this module accept a
`Subscription` instance and derive everything they need from it.

RADIUS tables used
------------------
radcheck  — per-user credential checks (password, Auth-Type)
radreply  — per-user attributes sent back to NAS (speed caps, IP)
radusergroup — maps username to a group (used for group-level policies)

Each subscriber's RADIUS username is their pppoe_username field.
Speed caps are stored as Mikrotik-Rate-Limit ("UL/DL") in radreply.
"""
import logging
from typing import Optional

from django.db import connections

logger = logging.getLogger(__name__)

# The Django DB alias for the RADIUS database
RADIUS_DB = "radius"


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _radius_execute(sql: str, params: tuple = ()):
    """Execute a parameterised query against the RADIUS database."""
    with connections[RADIUS_DB].cursor() as cursor:
        cursor.execute(sql, params)


def _radius_fetchall(sql: str, params: tuple = ()):
    with connections[RADIUS_DB].cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


# ── Public API ────────────────────────────────────────────────────────────────

def provision_subscriber(subscription) -> None:
    """
    Write RADIUS credentials for a newly activated subscription.
    Called when:
      - A new subscription is created (status → active)
      - A suspended subscription is reactivated

    Writes:
      radcheck: Cleartext-Password = pppoe_password
      radreply: Mikrotik-Rate-Limit = "UL/DL"
               Framed-IP-Address   = assigned static IP (if any)
      radusergroup: username → plan group name
    """
    subscriber = subscription.subscriber
    plan = subscription.plan
    username = subscriber.pppoe_username
    password = subscriber.pppoe_password

    logger.info(
        "RADIUS provision: username=%s plan=%s", username, plan.name
    )

    try:
        # 1. Clear any existing entries for this user (idempotent)
        deprovision_subscriber(subscription, log=False)

        # 2. radcheck — password
        _radius_execute(
            """
            INSERT INTO radcheck (username, attribute, op, value)
            VALUES (%s, 'Cleartext-Password', ':=', %s)
            """,
            (username, password),
        )

        # 3. radreply — speed cap (MikroTik-Rate-Limit)
        _radius_execute(
            """
            INSERT INTO radreply (username, attribute, op, value)
            VALUES (%s, 'Mikrotik-Rate-Limit', ':=', %s)
            """,
            (username, plan.radius_rate_limit),
        )

        # 4. radreply — static IP (if assigned)
        if subscription.assigned_ip:
            _radius_execute(
                """
                INSERT INTO radreply (username, attribute, op, value)
                VALUES (%s, 'Framed-IP-Address', ':=', %s)
                """,
                (username, subscription.assigned_ip.address),
            )

        # 5. radusergroup — map user to plan group
        group_name = _group_name(plan)
        _radius_execute(
            """
            INSERT INTO radusergroup (username, groupname, priority)
            VALUES (%s, %s, 1)
            ON CONFLICT (username, groupname) DO NOTHING
            """,
            (username, group_name),
        )

        logger.info("RADIUS provision complete for %s", username)

    except Exception as exc:
        logger.exception(
            "RADIUS provision FAILED for %s: %s", username, exc
        )
        raise


def suspend_subscriber(subscription, reason: str = "non-payment") -> None:
    """
    Suspend a subscriber by removing their active radcheck/radreply entries
    and adding a 'Auth-Type := Reject' entry so FreeRADIUS denies them.
    The original password is preserved in the Subscription model — we just
    block RADIUS auth here.
    """
    username = subscription.subscriber.pppoe_username
    logger.info("RADIUS suspend: username=%s reason=%s", username, reason)

    try:
        # Remove normal credentials
        deprovision_subscriber(subscription, log=False)

        # Insert explicit reject
        _radius_execute(
            """
            INSERT INTO radcheck (username, attribute, op, value)
            VALUES (%s, 'Auth-Type', ':=', 'Reject')
            ON CONFLICT DO NOTHING
            """,
            (username,),
        )

        logger.info("RADIUS suspend complete for %s", username)

    except Exception as exc:
        logger.exception(
            "RADIUS suspend FAILED for %s: %s", username, exc
        )
        raise


def reactivate_subscriber(subscription) -> None:
    """
    Reactivate a previously suspended subscriber.
    Removes the Reject entry and re-provisions full credentials.
    """
    username = subscription.subscriber.pppoe_username
    logger.info("RADIUS reactivate: username=%s", username)

    # Remove reject entry first, then re-provision
    _radius_execute(
        "DELETE FROM radcheck WHERE username=%s AND attribute='Auth-Type'",
        (username,),
    )
    provision_subscriber(subscription)


def deprovision_subscriber(subscription, log: bool = True) -> None:
    """
    Fully remove all RADIUS entries for a subscriber.
    Called on cancellation or before re-provisioning (idempotent reset).
    """
    username = subscription.subscriber.pppoe_username
    if log:
        logger.info("RADIUS deprovision: username=%s", username)

    try:
        _radius_execute(
            "DELETE FROM radcheck WHERE username=%s", (username,)
        )
        _radius_execute(
            "DELETE FROM radreply WHERE username=%s", (username,)
        )
        _radius_execute(
            "DELETE FROM radusergroup WHERE username=%s", (username,)
        )
    except Exception as exc:
        logger.exception(
            "RADIUS deprovision FAILED for %s: %s", username, exc
        )
        raise


def update_speed(subscription) -> None:
    """
    Update only the speed cap in radreply (called after a plan change).
    """
    username = subscription.subscriber.pppoe_username
    plan = subscription.plan
    logger.info(
        "RADIUS speed update: username=%s rate=%s",
        username, plan.radius_rate_limit,
    )
    try:
        _radius_execute(
            """
            UPDATE radreply SET value=%s
            WHERE username=%s AND attribute='Mikrotik-Rate-Limit'
            """,
            (plan.radius_rate_limit, username),
        )
        # If no row existed yet, insert it
        _radius_execute(
            """
            INSERT INTO radreply (username, attribute, op, value)
            SELECT %s, 'Mikrotik-Rate-Limit', ':=', %s
            WHERE NOT EXISTS (
                SELECT 1 FROM radreply
                WHERE username=%s AND attribute='Mikrotik-Rate-Limit'
            )
            """,
            (username, plan.radius_rate_limit, username),
        )
    except Exception as exc:
        logger.exception(
            "RADIUS speed update FAILED for %s: %s", username, exc
        )
        raise


def get_radius_status(username: str) -> Optional[str]:
    """
    Returns 'active', 'suspended', or None (not found) for a given username.
    Useful for quick dashboard checks.
    """
    rows = _radius_fetchall(
        "SELECT attribute, value FROM radcheck WHERE username=%s",
        (username,),
    )
    if not rows:
        return None
    for attr, val in rows:
        if attr == "Auth-Type" and val == "Reject":
            return "suspended"
    return "active"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _group_name(plan) -> str:
    """
    Build a RADIUS group name from the plan name.
    Lowercased, spaces replaced with underscores.
    e.g. "20 Mbps Unlimited" → "20_mbps_unlimited"
    """
    return plan.name.lower().replace(" ", "_").replace("-", "_")
