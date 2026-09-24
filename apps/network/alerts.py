"""
Alert evaluation for NetSuite-ISP network monitoring.

Called by the Celery task after each SNMP poll cycle completes for a tenant.
Evaluates all active AlertRules against current device state, applies
cooldown de-duplication, and sends email notifications.

De-duplication logic
---------------------
Before firing an alert, we check AlertEvent for a recent event for the
same (rule, device) pair within the cooldown window. If one exists the
alert is skipped. This prevents spam when a device stays down across
multiple poll cycles.
"""

import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def evaluate_alerts(schema_name: str) -> int:
    """
    Evaluate all active AlertRules for a tenant schema.
    Returns the number of alerts that fired.
    Called inside a schema_context block by the Celery task.
    """
    from .models import Device, AlertRule, AlertEvent, BandwidthSnapshot

    rules = AlertRule.objects.filter(is_active=True).select_related("device")
    fired = 0

    for rule in rules:
        # Scope: specific device or all devices
        if rule.device:
            devices = [rule.device]
        else:
            devices = list(Device.objects.filter(is_active=True))

        for device in devices:
            message = _check_condition(rule, device)
            if message is None:
                continue  # condition not met

            # De-duplication: skip if already fired within cooldown window
            cooldown_cutoff = timezone.now() - timedelta(minutes=rule.cooldown_minutes)
            already_fired = AlertEvent.objects.filter(
                rule=rule,
                device=device,
                fired_at__gte=cooldown_cutoff,
            ).exists()

            if already_fired:
                logger.debug(
                    "Alert '%s' for device '%s' in cooldown — skipping",
                    rule.name, device.name,
                )
                continue

            # Record the event
            event = AlertEvent.objects.create(
                rule=rule,
                device=device,
                message=message,
                email_sent=False,
            )

            # Send email notification
            email_sent = _send_alert_email(rule, device, message, schema_name)
            if email_sent:
                event.email_sent = True
                event.save(update_fields=["email_sent"])

            fired += 1
            logger.info(
                "Alert fired: rule='%s' device='%s' tenant='%s' email=%s",
                rule.name, device.name, schema_name, email_sent,
            )

    return fired


def _check_condition(rule, device) -> str | None:
    """
    Check whether a rule's condition is met for a device.
    Returns a human-readable alert message, or None if condition is not met.
    """
    from .models import BandwidthSnapshot

    if rule.condition == "device_down":
        if device.status == "down":
            return (
                f"Device '{device.name}' ({device.ip_address}) is DOWN. "
                f"Location: {device.location or 'unknown'}. "
                f"Last seen: {device.last_seen.strftime('%Y-%m-%d %H:%M') if device.last_seen else 'never'}."
            )

    elif rule.condition == "device_up":
        if device.status == "up":
            return (
                f"Device '{device.name}' ({device.ip_address}) has RECOVERED (UP). "
                f"Location: {device.location or 'unknown'}."
            )

    elif rule.condition == "high_bandwidth" and rule.threshold_mbps:
        # Check latest bandwidth snapshot
        latest = BandwidthSnapshot.objects.filter(device=device).first()
        if latest:
            # Convert bytes/s to Mbps (approximate — counter delta would be more accurate,
            # but for alerting a threshold on raw octets is sufficient)
            bytes_total = latest.bytes_in + latest.bytes_out
            mbps = (bytes_total * 8) / (1024 * 1024)
            if mbps > rule.threshold_mbps:
                return (
                    f"High bandwidth on '{device.name}' ({device.ip_address}): "
                    f"{mbps:.1f} Mbps (threshold: {rule.threshold_mbps} Mbps)."
                )

    return None


def _send_alert_email(rule, device, message: str, schema_name: str) -> bool:
    """
    Send an email alert notification. Returns True on success.
    Logs and returns False on failure — never raises.
    """
    subject = f"[Emmsuite ISP Alert] {rule.name} — {device.name}"
    body = (
        f"Alert: {rule.name}\n"
        f"Tenant: {schema_name}\n"
        f"Device: {device.name} ({device.ip_address})\n"
        f"Type: {device.get_device_type_display()}\n"
        f"Location: {device.location or 'unknown'}\n\n"
        f"{message}\n\n"
        f"— Emmsuite ISP Monitoring\n"
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL or "alerts@emmsuite.io",
            recipient_list=[rule.notify_email],
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error(
            "Failed to send alert email to %s for rule '%s': %s",
            rule.notify_email, rule.name, exc,
        )
        return False
