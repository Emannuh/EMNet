"""
Network management domain models.
Devices, uptime events, and bandwidth snapshots (per-tenant schema).
"""
from django.db import models


class Device(models.Model):
    """A managed network device belonging to the ISP."""

    class DeviceType(models.TextChoices):
        ROUTER = "router", "Router"
        SWITCH = "switch", "Switch"
        AP = "ap", "Access Point"
        ONT = "ont", "ONT"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        UNKNOWN = "unknown", "Unknown"

    name = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(max_length=10, choices=DeviceType.choices, default=DeviceType.OTHER)
    location = models.CharField(max_length=200, blank=True)
    snmp_community = models.CharField(max_length=100, default="public")
    snmp_version = models.CharField(max_length=5, default="2c")

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNKNOWN)
    last_seen = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("ip_address",)]

    def __str__(self):
        return f"{self.name} ({self.ip_address}) [{self.get_status_display()}]"


class UptimeEvent(models.Model):
    """Records a status change (up/down) for a device."""

    class EventType(models.TextChoices):
        UP = "up", "Came Up"
        DOWN = "down", "Went Down"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="uptime_events")
    event_type = models.CharField(max_length=5, choices=EventType.choices)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.device.name} {self.event_type} @ {self.timestamp:%Y-%m-%d %H:%M}"


class BandwidthSnapshot(models.Model):
    """
    Point-in-time bandwidth reading per device interface.
    Stored in TimescaleDB hypertable (migration will enable this).
    """
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="bandwidth_snapshots")
    interface = models.CharField(max_length=50)
    bytes_in = models.BigIntegerField(default=0)
    bytes_out = models.BigIntegerField(default=0)
    timestamp = models.DateTimeField()  # set explicitly by SNMP poller

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["device", "timestamp"])]

    def __str__(self):
        return f"{self.device.name}/{self.interface} @ {self.timestamp:%H:%M:%S}"


# ── Alert Rules ───────────────────────────────────────────────────────────────

class AlertRule(models.Model):
    """
    Defines a condition that triggers an alert notification.
    Evaluated by the Celery alert task after each SNMP poll cycle.
    """

    class Condition(models.TextChoices):
        DEVICE_DOWN    = "device_down",    "Device Down"
        DEVICE_UP      = "device_up",      "Device Up (recovery)"
        HIGH_BANDWIDTH = "high_bandwidth", "High Bandwidth Usage"

    name        = models.CharField(max_length=150)
    condition   = models.CharField(max_length=20, choices=Condition.choices)
    # Optional: scope to a specific device; if null applies to ALL devices
    device      = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        null=True, blank=True, related_name="alert_rules",
    )
    # Threshold only used for HIGH_BANDWIDTH (Mbps)
    threshold_mbps = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="For high_bandwidth: alert when Mbps exceeds this value",
    )
    # Notification target
    notify_email = models.EmailField(
        help_text="Email address to notify when this rule fires",
    )
    # Cooldown: minimum minutes between repeated alerts for the same device+rule
    cooldown_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Minimum minutes between repeated alerts for the same device",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        scope = self.device.name if self.device else "all devices"
        return f"{self.name} [{self.condition}] → {scope}"


class AlertEvent(models.Model):
    """
    Records each time an AlertRule fired.
    Used for de-duplication — if a recent AlertEvent exists within the
    cooldown window, the rule does not fire again.
    """
    rule       = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="events")
    device     = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="alert_events")
    message    = models.TextField()
    fired_at   = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fired_at"]

    def __str__(self):
        return f"{self.rule.name} @ {self.device.name} [{self.fired_at:%Y-%m-%d %H:%M}]"
