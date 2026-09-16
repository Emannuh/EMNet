from django.contrib import admin
from .models import Device, UptimeEvent, BandwidthSnapshot


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "ip_address", "device_type", "status", "location", "last_seen"]
    list_filter = ["device_type", "status", "is_active"]
    search_fields = ["name", "ip_address", "location"]


@admin.register(UptimeEvent)
class UptimeEventAdmin(admin.ModelAdmin):
    list_display = ["device", "event_type", "timestamp"]
    list_filter = ["event_type"]
    readonly_fields = ["timestamp"]


@admin.register(BandwidthSnapshot)
class BandwidthSnapshotAdmin(admin.ModelAdmin):
    list_display = ["device", "interface", "bytes_in", "bytes_out", "timestamp"]
    readonly_fields = ["timestamp"]
