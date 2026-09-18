"""
Subscriber Management domain models.
Covers fixed/fiber ISP customers — service plans, subscriber accounts,
subscriptions, IP pool, invoices, and payments (per-tenant schema).
"""
import uuid
from datetime import date
from dateutil.relativedelta import relativedelta

from django.db import models
from django.utils import timezone


# ── Service Plans ─────────────────────────────────────────────────────────────

class ServicePlan(models.Model):
    """
    A recurring service plan offered to fixed/fiber subscribers.
    e.g. "20 Mbps Unlimited – KES 3,500/month"
    Speed limits are written to FreeRADIUS radreply as RADIUS attributes.
    """
    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"

    class ConnectionType(models.TextChoices):
        PPPOE = "pppoe", "PPPoE"
        STATIC_IP = "static", "Static IP"
        DHCP_MAC = "dhcp_mac", "DHCP + MAC Binding"

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    connection_type = models.CharField(
        max_length=10, choices=ConnectionType.choices, default=ConnectionType.PPPOE
    )
    # Speed caps (used to generate RADIUS Mikrotik-Rate-Limit attribute)
    download_mbps = models.PositiveIntegerField(help_text="Download speed in Mbps")
    upload_mbps = models.PositiveIntegerField(help_text="Upload speed in Mbps")
    # Billing
    price_kes = models.DecimalField(max_digits=10, decimal_places=2)
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    # Grace period before auto-suspend after due date
    grace_days = models.PositiveSmallIntegerField(
        default=3, help_text="Days after due date before auto-suspend"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["price_kes"]

    def __str__(self):
        return f"{self.name} – KES {self.price_kes}/{self.billing_cycle}"

    @property
    def radius_rate_limit(self) -> str:
        """MikroTik rate-limit string: 'UL/DL' e.g. '5M/20M'."""
        return f"{self.upload_mbps}M/{self.download_mbps}M"

    def next_due_date(self, from_date: date) -> date:
        """Calculate next billing due date from a given date."""
        if self.billing_cycle == self.BillingCycle.MONTHLY:
            return from_date + relativedelta(months=1)
        elif self.billing_cycle == self.BillingCycle.QUARTERLY:
            return from_date + relativedelta(months=3)
        else:  # annual
            return from_date + relativedelta(years=1)


# ── IP Pool ───────────────────────────────────────────────────────────────────

class IpPool(models.Model):
    """
    A pool of IP addresses the ISP can assign to static-IP subscribers.
    """
    name = models.CharField(max_length=100)
    network = models.CharField(max_length=18, help_text="e.g. 192.168.10.0/24")
    gateway = models.GenericIPAddressField()
    dns_primary = models.GenericIPAddressField(default="8.8.8.8")
    dns_secondary = models.GenericIPAddressField(default="8.8.4.4")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.network})"

    @property
    def assigned_count(self):
        return self.assigned_ips.count()


class IpAddress(models.Model):
    """
    An individual IP address within a pool.
    Assigned to a subscriber on subscription activation.
    """
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        ASSIGNED = "assigned", "Assigned"
        RESERVED = "reserved", "Reserved"

    pool = models.ForeignKey(IpPool, on_delete=models.CASCADE, related_name="assigned_ips")
    address = models.GenericIPAddressField(unique=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.AVAILABLE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["address"]

    def __str__(self):
        return f"{self.address} [{self.status}]"


# ── Subscribers ───────────────────────────────────────────────────────────────

class Subscriber(models.Model):
    """
    An ISP's fixed/fiber customer. One subscriber can have one active
    subscription at a time.
    """
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"
        PENDING = "pending", "Pending Activation"

    # Personal details
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20)
    id_number = models.CharField(
        max_length=50, blank=True, help_text="National ID or passport number"
    )

    # Installation address
    address = models.TextField()
    gps_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    gps_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )

    # CPE / ONT details
    cpe_serial = models.CharField(
        max_length=100, blank=True, help_text="CPE or ONT serial number"
    )
    cpe_mac = models.CharField(
        max_length=17, blank=True, help_text="CPE MAC address (XX:XX:XX:XX:XX:XX)"
    )

    # PPPoE credentials (written to RADIUS radcheck)
    pppoe_username = models.CharField(
        max_length=100, unique=True,
        help_text="PPPoE / RADIUS username — must be unique across all subscribers"
    )
    pppoe_password = models.CharField(max_length=100)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )

    # Notes
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.pppoe_username})"

    @property
    def active_subscription(self):
        return self.subscriptions.filter(
            status=Subscription.Status.ACTIVE
        ).first()

    @property
    def unpaid_invoices_count(self):
        return Invoice.objects.filter(
            subscription__subscriber=self,
            status__in=[Invoice.Status.UNPAID, Invoice.Status.OVERDUE]
        ).count()


# ── Subscriptions ─────────────────────────────────────────────────────────────

class Subscription(models.Model):
    """
    Links a subscriber to a service plan for a billing cycle.
    One active subscription per subscriber at a time.
    """
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(
        ServicePlan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    # Assigned static IP (nullable — PPPoE may use dynamic IP)
    assigned_ip = models.OneToOneField(
        IpAddress, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="subscription"
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    start_date = models.DateField(default=date.today)
    next_due_date = models.DateField()
    suspended_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.subscriber.full_name} → {self.plan.name} [{self.status}]"
        )

    def save(self, *args, **kwargs):
        # Auto-set next_due_date on first save if not provided
        if not self.next_due_date:
            self.next_due_date = self.plan.next_due_date(self.start_date)
        super().save(*args, **kwargs)


# ── Invoices ──────────────────────────────────────────────────────────────────

class Invoice(models.Model):
    """Monthly (or cycle-based) invoice for a subscription."""

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="invoices"
    )
    amount_kes = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.UNPAID
    )
    # M-Pesa STK push tracking
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"INV-{str(self.reference)[:8].upper()} "
            f"{self.subscription.subscriber.full_name} "
            f"KES {self.amount_kes} [{self.status}]"
        )

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == self.Status.UNPAID
            and date.today() > self.due_date
        )


# ── Invoice Payments ──────────────────────────────────────────────────────────

class InvoicePayment(models.Model):
    """
    Records an M-Pesa payment made against an invoice.
    A single invoice can have multiple partial payment attempts
    but only one completed payment.
    """
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments"
    )
    phone_number = models.CharField(max_length=20)
    amount_kes = models.DecimalField(max_digits=10, decimal_places=2)
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Payment {self.mpesa_receipt_number or 'pending'} "
            f"KES {self.amount_kes} [{self.status}]"
        )
