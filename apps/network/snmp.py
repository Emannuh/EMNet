"""
SNMP GET helper for NetSuite-ISP network polling.

Uses pysnmp 6.x hlapi.asyncio API.
Wraps the async call in asyncio.run() so it can be called from a
synchronous Celery task without touching the task's event loop.

OIDs polled per device
----------------------
sysUpTime       1.3.6.1.2.1.1.3.0          — device uptime (hundredths of seconds)
ifInOctets      1.3.6.1.2.1.2.2.1.10.1     — bytes in  on interface index 1
ifOutOctets     1.3.6.1.2.1.2.2.1.16.1     — bytes out on interface index 1
ifDescr         1.3.6.1.2.1.2.2.1.2.1      — interface name (e.g. eth0)

Returns
-------
dict with keys:
    reachable    bool
    interface    str     e.g. "eth0"
    bytes_in     int     ifInOctets counter value
    bytes_out    int     ifOutOctets counter value
    uptime_ticks int     sysUpTime in hundredths of seconds (0 if unavailable)
    error        str     error message when reachable=False
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# OIDs
OID_SYSUPTIME    = "1.3.6.1.2.1.1.3.0"
OID_IFDESCR      = "1.3.6.1.2.1.2.2.1.2.1"
OID_IFINOCTETS   = "1.3.6.1.2.1.2.2.1.10.1"
OID_IFOUTOCTETS  = "1.3.6.1.2.1.2.2.1.16.1"

TIMEOUT_SECONDS  = 3    # per SNMP request
RETRIES          = 1    # number of SNMP retries


async def _snmp_get_async(
    ip: str,
    community: str,
    version: str,
    oids: list[str],
) -> Optional[dict[str, int]]:
    """
    Perform a synchronous SNMP GET for a list of OIDs.
    Returns {oid: value} dict or None on timeout/error.
    """
    from pysnmp.hlapi.asyncio import (
        getCmd, SnmpEngine, CommunityData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
    )

    mp_model = 1 if version == "2c" else 0  # 0=v1, 1=v2c (v3 not handled here)

    object_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]

    try:
        error_indication, error_status, error_index, var_binds = await getCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=mp_model),
            await UdpTransportTarget.create(
                (ip, 161),
                timeout=TIMEOUT_SECONDS,
                retries=RETRIES,
            ),
            ContextData(),
            *object_types,
        )
    except Exception as exc:
        logger.debug("SNMP GET exception for %s: %s", ip, exc)
        return None

    if error_indication:
        logger.debug("SNMP error for %s: %s", ip, error_indication)
        return None

    if error_status:
        logger.debug(
            "SNMP PDU error for %s at %s: %s",
            ip, error_index, error_status.prettyPrint(),
        )
        return None

    result = {}
    for var_bind in var_binds:
        oid_str = str(var_bind[0])
        val = var_bind[1]
        # Strip the leading dot prefix pysnmp sometimes adds
        for query_oid in oids:
            if oid_str.endswith(query_oid.lstrip(".")):
                try:
                    result[query_oid] = int(val)
                except Exception:
                    result[query_oid] = 0
                break

    return result


def snmp_poll_device(device) -> dict:
    """
    Poll a single device via SNMP. Called from the Celery task.
    Returns the standard result dict expected by poll_single_device.

    If the device is unreachable or SNMP times out, returns reachable=False
    immediately — does NOT raise.
    """
    ip        = str(device.ip_address)
    community = device.snmp_community or "public"
    version   = device.snmp_version or "2c"

    oids = [OID_SYSUPTIME, OID_IFDESCR, OID_IFINOCTETS, OID_IFOUTOCTETS]

    try:
        result = asyncio.run(_snmp_get_async(ip, community, version, oids))
    except Exception as exc:
        logger.warning("asyncio.run failed for device %s (%s): %s", device.name, ip, exc)
        result = None

    if result is None:
        logger.info("Device %s (%s) unreachable via SNMP", device.name, ip)
        return {
            "reachable":    False,
            "interface":    "",
            "bytes_in":     0,
            "bytes_out":    0,
            "uptime_ticks": 0,
            "error":        "SNMP timeout or unreachable",
        }

    interface    = _oid_str_value(ip, OID_IFDESCR,     result, "eth0")
    bytes_in     = result.get(OID_IFINOCTETS,  0)
    bytes_out    = result.get(OID_IFOUTOCTETS, 0)
    uptime_ticks = result.get(OID_SYSUPTIME,   0)

    logger.debug(
        "SNMP polled %s (%s): in=%d out=%d uptime=%d",
        device.name, ip, bytes_in, bytes_out, uptime_ticks,
    )
    return {
        "reachable":    True,
        "interface":    interface if isinstance(interface, str) else "eth0",
        "bytes_in":     bytes_in,
        "bytes_out":    bytes_out,
        "uptime_ticks": uptime_ticks,
        "error":        "",
    }


def _oid_str_value(ip, oid, result, default):
    """Return the string value of an OID from the result dict."""
    val = result.get(oid, default)
    if val == default:
        return default
    try:
        return val.decode() if isinstance(val, bytes) else str(val)
    except Exception:
        return default
