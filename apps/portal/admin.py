from django.contrib import admin
from .models import VoucherPlan, Voucher, WifiSession


@admin.register(VoucherPlan)
class VoucherPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "duration_minutes", "data_mb", "price_kes", "is_active"]
    list_filter = ["is_active"]


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ["code", "plan", "status", "phone_number", "created_at", "expires_at"]
    list_filter = ["status"]
    search_fields = ["code", "phone_number", "mac_address"]
    readonly_fields = ["code", "created_at"]


@admin.register(WifiSession)
class WifiSessionAdmin(admin.ModelAdmin):
    list_display = ["voucher", "nas_ip", "mac_address", "started_at", "ended_at"]
    readonly_fields = ["started_at"]
