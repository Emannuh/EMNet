"""
SNMP polling Celery tasks for NetSuite-ISP.

Architecture
------------
- `poll_all_tenants`  — Beat-scheduled entry point; iterates every active
                        tenant and dispatches a per-tenant subtask.
- `poll_tenant_devices` — Runs inside the tenant's Postgres schema; polls
                          each active Device via SNMP and writes results.
- `poll_single_device`  — Low-level helper; does the actual SNMP GET and
                          persists a BandwidthSnapshot + UptimeEvent if
                          the status changed.

Integration status: SKELETON
-----------------------------
The SNMP calls are stubbed with a TODO comment.  Real pysnmp calls will be
wired in when we do the integration pass.  Everything else (tenant switching,
DB writes, Beat schedule) is production-ready.
"""
import logging
from datetime import datetime, timezone

from celery import shared_task
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


# ── Entry point (Beat-scheduled) ─────────────────────────────────────────────

@shared_task(bind=True, name="network.poll_all_tenants", ignore_result=True)
def poll_all_tenants(self):
    """
    Iterate every active tenant and dispatch a polling subtask for each.
    Runs in the PUBLIC schema — no tenant context needed here.
    """
    try:
        from django_tenants.utils import get_tenant_model, schema_context
        TenantModel = get_tenant_model()

        active_tenants = TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        )
        logger.info("SNMP poll: found %d active tenants", active_tenants.count())

        for tenant in active_tenants:
            poll_tenant_devices.delay(tenant.schema_name)

    except Exception as exc:
        logger.exception("poll_all_tenants failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=3)


# ── Per-tenant poller ─────────────────────────────────────────────────────────

@shared_task(bind=True, name="network.poll_tenant_devices", ignore_result=True)
def poll_tenant_devices(self, schema_name: str):
    """
    Switch to the tenant schema and poll every active device.
    """
    try:
        from django_tenants.utils import schema_context
        from .models import Device

        with schema_context(schema_name):
            devices = Device.objects.filter(is_active=True)
            logger.info(
                "Polling %d devices for tenant '%s'", devices.count(), schema_name
            )
            for device in devices:
                poll_single_device.delay(schema_name, device.pk)

    except Exception as exc:
        logger.exception(
            "poll_tenant_devices failed for '%s': %s", schema_name, exc
        )
        raise self.retry(exc=exc, countdown=30, max_retries=3)


# ── Single-device poller ──────────────────────────────────────────────────────

@shared_task(bind=True, name="network.poll_single_device", ignore_result=True)
def poll_single_device(self, schema_name: str, device_pk: int):
    """
    Poll one device via SNMP, persist a BandwidthSnapshot, and update
    Device.status + Device.last_seen.  Writes a UptimeEvent if the status
    changed (up→down or down→up).
    """
    try:
        from django_tenants.utils import schema_context
        from .models import Device, BandwidthSnapshot, UptimeEvent

        with schema_context(schema_name):
            try:
                device = Device.objects.get(pk=device_pk)
            except Device.DoesNotExist:
                logger.warning(
                    "poll_single_device: device %d not found in '%s'",
                    device_pk, schema_name,
                )
                return

            previous_status = device.status
            now = dj_timezone.now()

            # ── SNMP GET ─────────────────────────────────────────────────────
            # TODO (integration): replace stub with real pysnmp call.
            # Expected return value:
            #   snmp_result = {
            #       "reachable": bool,
            #       "interface": str,        # e.g. "eth0"
            #       "bytes_in": int,         # ifInOctets
            #       "bytes_out": int,        # ifOutOctets
            #   }
            snmp_result = _snmp_get_stub(device)
            # ─────────────────────────────────────────────────────────────────

            if snmp_result["reachable"]:
                new_status = Device.Status.UP
                device.last_seen = now

                # Persist bandwidth snapshot
                BandwidthSnapshot.objects.create(
                    device=device,
                    interface=snmp_result["interface"],
                    bytes_in=snmp_result["bytes_in"],
                    bytes_out=snmp_result["bytes_out"],
                    timestamp=now,
                )
            else:
                new_status = Device.Status.DOWN

            # Detect status change and record event
            if new_status != previous_status:
                UptimeEvent.objects.create(
                    device=device,
                    event_type=new_status,
                    note=f"Status changed from {previous_status} to {new_status}",
                )
                logger.info(
                    "Device '%s' (%s) changed: %s → %s",
                    device.name, device.ip_address, previous_status, new_status,
                )

            device.status = new_status
            device.save(update_fields=["status", "last_seen", "updated_at"])

    except Exception as exc:
        logger.exception(
            "poll_single_device failed for device %d in '%s': %s",
            device_pk, schema_name, exc,
        )
        raise self.retry(exc=exc, countdown=30, max_retries=2)


# ── SNMP stub (replace with real pysnmp in integration pass) ─────────────────

def _snmp_get_stub(device) -> dict:
    """
    Placeholder SNMP GET.
    Returns a fake reachable=True result so the task pipeline can be
    tested end-to-end without real devices.

    Replace this function body with a real pysnmp GET when integrating:

        from pysnmp.hlapi import (
            getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
            ContextData, ObjectType, ObjectIdentity,
        )
        # OID 1.3.6.1.2.1.2.2.1.10.1 = ifInOctets for interface index 1
        # OID 1.3.6.1.2.1.2.2.1.16.1 = ifOutOctets for interface index 1
        ...
    """
    logger.debug(
        "SNMP stub: pretending device '%s' (%s) is reachable",
        device.name, device.ip_address,
    )
    return {
        "reachable": True,
        "interface": "eth0",
        "bytes_in": 0,
        "bytes_out": 0,
    }
