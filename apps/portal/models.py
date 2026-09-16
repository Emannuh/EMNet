"""
Captive portal domain models.
Voucher plans, vouchers, and active WiFi sessions live here (per-tenant schema).
"""
from django.db import models
import uuid


class VoucherPlan(models.Model):
    """A purchasable plan offered by the ISP (e.g. '1 Hour – KES 20')."""

    name = models.CharField(max_length=100)
    # Either time-based or data-based (or both)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    data_mb = models.PositiveIntegerField(null=True, blank=True)
    price_kes = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price_kes"]

    def __str__(self):
        return f"{self.name} @ KES {self.price_kes}"


class Voucher(models.Model):
    """A single-use token that grants access once redeemed."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Payment"
        ACTIVE = "active", "Active"
        USED = "used", "Used"
        EXPIRED = "expired", "Expired"

    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    plan = models.ForeignKey(VoucherPlan, on_delete=models.PROTECT, related_name="vouchers")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    phone_number = models.CharField(max_length=20, blank=True)  # buyer's M-Pesa number
    mac_address = models.CharField(max_length=17, blank=True)   # device MAC on redemption

    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} [{self.status}]"


class WifiSession(models.Model):
    """Tracks an active RADIUS-authenticated session."""

    voucher = models.OneToOneField(Voucher, on_delete=models.PROTECT, related_name="session")
    nas_ip = models.GenericIPAddressField()
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=17)

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    bytes_in = models.BigIntegerField(default=0)
    bytes_out = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Session {self.voucher.code} on {self.nas_ip}"
