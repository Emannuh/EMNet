"""
Billing domain models.
M-Pesa payments and invoices per-tenant schema.
"""
from django.db import models
import uuid


class Payment(models.Model):
    """Records an M-Pesa STK Push transaction."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # M-Pesa fields
    phone_number = models.CharField(max_length=20)
    amount_kes = models.DecimalField(max_digits=10, decimal_places=2)
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.TextField(blank=True)

    # Link to what was purchased (nullable — set after voucher created)
    voucher_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.reference} [{self.status}] KES {self.amount_kes}"
