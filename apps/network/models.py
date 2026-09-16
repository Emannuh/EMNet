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
