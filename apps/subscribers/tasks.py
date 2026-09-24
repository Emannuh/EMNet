"""
Subscriber billing Celery tasks.

Task tree (all Beat-scheduled)
--------------------------------
generate_invoices_for_all_tenants   — daily 06:00 EAT
  └─ generate_invoices_for_tenant   — per tenant
       └─ generate_invoice_for_subscription — per due subscription

send_payment_reminders_for_all_tenants — daily 08:00 EAT
  └─ send_payment_reminder_for_tenant

check_overdue_for_all_tenants       — daily 09:00 EAT
  └─ check_overdue_for_tenant
       └─ mark_invoice_overdue + trigger_auto_suspend

process_mpesa_callback              — called by FastAPI callback endpoint
"""
import logging
from datetime import date, timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INVOICE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="subscribers.generate_invoices_for_all_tenants",
             ignore_result=True)
def generate_invoices_for_all_tenants(self):
    """Entry point: dispatch per-tenant invoice generation."""
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        )
        logger.info("Invoice generation: %d tenants", tenants.count())
        for tenant in tenants:
            generate_invoices_for_tenant.delay(tenant.schema_name)
    except Exception as exc:
        logger.exception("generate_invoices_for_all_tenants failed: %s", exc)
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@shared_task(bind=True, name="subscribers.generate_invoices_for_tenant",
             ignore_result=True)
def generate_invoices_for_tenant(self, schema_name: str):
    """
    For each active subscription whose next_due_date is today,
    generate an invoice if one doesn't already exist for this period.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .models import Subscription, Invoice
            today = date.today()

            due_subs = Subscription.objects.filter(
                status=Subscription.Status.ACTIVE,
                next_due_date__lte=today,
            ).select_related("subscriber", "plan")

            for sub in due_subs:
                # Avoid duplicate invoices for the same period
                already_exists = Invoice.objects.filter(
                    subscription=sub,
                    period_start=sub.next_due_date,
                ).exists()
                if not already_exists:
                    generate_invoice_for_subscription.delay(
                        schema_name, sub.pk
                    )

    except Exception as exc:
        logger.exception(
            "generate_invoices_for_tenant failed (%s): %s", schema_name, exc
        )
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@shared_task(bind=True, name="subscribers.generate_invoice_for_subscription",
             ignore_result=True)
def generate_invoice_for_subscription(self, schema_name: str, subscription_pk: int):
    """
    Create an Invoice record for one subscription and immediately
    dispatch an STK Push to collect payment.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .models import Subscription, Invoice

            try:
                sub = Subscription.objects.select_related(
                    "subscriber", "plan"
                ).get(pk=subscription_pk)
            except Subscription.DoesNotExist:
                logger.warning(
                    "Subscription %d not found in %s", subscription_pk, schema_name
                )
                return

            plan = sub.plan
            period_start = sub.next_due_date
            period_end = plan.next_due_date(period_start) - timedelta(days=1)

            invoice = Invoice.objects.create(
                subscription=sub,
                amount_kes=plan.price_kes,
                due_date=period_start,
                period_start=period_start,
                period_end=period_end,
                status=Invoice.Status.UNPAID,
            )

            # Advance next_due_date on the subscription
            sub.next_due_date = plan.next_due_date(period_start)
            sub.save(update_fields=["next_due_date", "updated_at"])

            logger.info(
                "Invoice %s created for %s (KES %s)",
                invoice.reference, sub.subscriber.full_name, invoice.amount_kes,
            )

            # Trigger STK Push immediately
            if sub.subscriber.phone:
                send_stk_push_for_invoice.delay(
                    schema_name, invoice.pk
                )

    except Exception as exc:
        logger.exception(
            "generate_invoice_for_subscription failed (%s, sub=%d): %s",
            schema_name, subscription_pk, exc,
        )
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ─────────────────────────────────────────────────────────────────────────────
# M-PESA STK PUSH
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="subscribers.send_stk_push_for_invoice",
             ignore_result=True)
def send_stk_push_for_invoice(self, schema_name: str, invoice_pk: int):
    """
    Send an M-Pesa STK Push to the subscriber's phone for a given invoice.
    On success, store the checkout_request_id on the invoice so the
    callback can match it back.

    Integration status: STUB
    ------------------------
    Replace the TODO block with a real MpesaService call when wiring
    up the Daraja API (same service used by the voucher billing flow).
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .models import Invoice, InvoicePayment

            try:
                invoice = Invoice.objects.select_related(
                    "subscription__subscriber", "subscription__plan"
                ).get(pk=invoice_pk)
            except Invoice.DoesNotExist:
                logger.warning(
                    "Invoice %d not found in %s", invoice_pk, schema_name
                )
                return

            if invoice.status == Invoice.Status.PAID:
                return  # Already paid, nothing to do

            subscriber = invoice.subscription.subscriber
            phone = subscriber.phone

            # Normalise phone: 07XXXXXXXX → 2547XXXXXXXX
            if phone.startswith("0"):
                phone = "254" + phone[1:]
            elif not phone.startswith("254"):
                phone = "254" + phone

            logger.info(
                "STK Push: invoice=%s subscriber=%s phone=%s amount=%s",
                invoice.reference, subscriber.full_name,
                phone, invoice.amount_kes,
            )

            # ── Real M-Pesa STK Push ──────────────────────────────────────
            try:
                from apps.billing.mpesa import stk_push, MpesaNotConfigured, MpesaApiError
                result = stk_push(
                    phone=phone,
                    amount=int(invoice.amount_kes),
                    account_ref=str(invoice.reference)[:12].upper(),
                    description=f"Internet {invoice.period_start}",
                    callback_path="/payments/callback",
                )
                checkout_request_id = result["CheckoutRequestID"]
                logger.info(
                    "STK Push dispatched for invoice %s: checkout_id=%s",
                    invoice.reference, checkout_request_id,
                )
            except MpesaNotConfigured as exc:
                # Credentials not set — log clearly, don't crash the task
                logger.error(
                    "M-Pesa not configured for invoice %s: %s. "
                    "Set MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_PASSKEY in .env",
                    invoice.reference, exc,
                )
                return
            except MpesaApiError as exc:
                logger.error(
                    "Daraja API error for invoice %s: %s",
                    invoice.reference, exc,
                )
                raise self.retry(exc=exc, countdown=120, max_retries=3)
            # ─────────────────────────────────────────────────────────────

            # Record the pending payment attempt
            InvoicePayment.objects.create(
                invoice=invoice,
                phone_number=phone,
                amount_kes=invoice.amount_kes,
                mpesa_checkout_request_id=checkout_request_id,
                status=InvoicePayment.Status.PENDING,
            )

            # Store checkout_request_id on invoice for callback matching
            invoice.mpesa_checkout_request_id = checkout_request_id
            invoice.save(update_fields=["mpesa_checkout_request_id", "updated_at"])

    except Exception as exc:
        logger.exception(
            "send_stk_push_for_invoice failed (%s, inv=%d): %s",
            schema_name, invoice_pk, exc,
        )
        raise self.retry(exc=exc, countdown=120, max_retries=3)


@shared_task(bind=True, name="subscribers.process_invoice_payment_callback",
             ignore_result=True)
def process_invoice_payment_callback(
    self,
    schema_name: str,
    checkout_request_id: str,
    result_code: int,
    receipt_number: str = "",
    failure_reason: str = "",
):
    """
    Called by the M-Pesa callback endpoint after Daraja posts the result.
    Marks the invoice paid and reactivates the subscriber if suspended.

    Race condition protection: uses select_for_update() on Subscription
    so that the overdue-check task and this callback cannot both read
    stale status and diverge. The transaction covers the full
    read-check-write cycle.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from django.db import transaction
            from .models import Invoice, InvoicePayment, Subscription, Subscriber
            from .radius_service import reactivate_subscriber

            try:
                payment = InvoicePayment.objects.select_related(
                    "invoice__subscription__subscriber",
                    "invoice__subscription__plan",
                ).get(mpesa_checkout_request_id=checkout_request_id)
            except InvoicePayment.DoesNotExist:
                logger.warning(
                    "No InvoicePayment found for checkout_request_id=%s",
                    checkout_request_id,
                )
                return

            invoice = payment.invoice

            if result_code == 0:
                with transaction.atomic():
                    # Lock the subscription row for the duration of this block
                    # so check_overdue_for_tenant cannot suspend between our
                    # status read and our status write.
                    subscription = Subscription.objects.select_for_update().get(
                        pk=invoice.subscription_id
                    )
                    subscriber = Subscriber.objects.select_for_update().get(
                        pk=subscription.subscriber_id
                    )

                    # Re-fetch invoice inside the lock
                    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
                    if invoice.status == Invoice.Status.PAID:
                        # Already processed (duplicate callback) — idempotent exit
                        logger.info(
                            "Invoice %s already PAID — duplicate callback ignored",
                            invoice.reference,
                        )
                        return

                    payment.status = InvoicePayment.Status.COMPLETED
                    payment.mpesa_receipt_number = receipt_number
                    payment.save(update_fields=["status", "mpesa_receipt_number", "updated_at"])

                    invoice.status = Invoice.Status.PAID
                    invoice.save(update_fields=["status", "updated_at"])

                    logger.info(
                        "Invoice %s PAID — receipt %s subscriber %s",
                        invoice.reference, receipt_number, subscriber.full_name,
                    )

                    was_suspended = subscription.status == Subscription.Status.SUSPENDED

                    if was_suspended:
                        subscription.status = Subscription.Status.ACTIVE
                        subscription.suspended_at = None
                        subscription.suspension_reason = ""
                        subscription.save(update_fields=[
                            "status", "suspended_at", "suspension_reason", "updated_at"
                        ])
                        subscriber.status = Subscriber.Status.ACTIVE
                        subscriber.save(update_fields=["status", "updated_at"])

                # RADIUS call outside the DB transaction (external I/O)
                if was_suspended:
                    try:
                        reactivate_subscriber(subscription)
                        logger.info(
                            "Subscriber %s reactivated after payment", subscriber.full_name
                        )
                    except Exception as radius_exc:
                        # RADIUS failure after DB commit: log and alert but don't
                        # roll back the payment — operator must manually re-provision.
                        logger.error(
                            "RADIUS reactivation failed for %s after payment. "
                            "Manual re-provision required. Error: %s",
                            subscriber.pppoe_username, radius_exc,
                        )

            else:
                # Payment failed — no locking needed, just record failure
                payment.status = InvoicePayment.Status.FAILED
                payment.failure_reason = failure_reason
                payment.save(update_fields=["status", "failure_reason", "updated_at"])
                logger.warning(
                    "Invoice %s payment FAILED — reason: %s",
                    invoice.reference, failure_reason,
                )

    except Exception as exc:
        logger.exception(
            "process_invoice_payment_callback failed (%s, %s): %s",
            schema_name, checkout_request_id, exc,
        )
        raise self.retry(exc=exc, countdown=30, max_retries=3)


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENT REMINDERS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="subscribers.send_payment_reminders_for_all_tenants",
             ignore_result=True)
def send_payment_reminders_for_all_tenants(self):
    """Send payment reminders across all tenants (daily)."""
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        for tenant in TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        ):
            send_payment_reminders_for_tenant.delay(tenant.schema_name)
    except Exception as exc:
        logger.exception("send_payment_reminders_for_all_tenants: %s", exc)
        raise self.retry(exc=exc, countdown=300, max_retries=2)


@shared_task(bind=True, name="subscribers.send_payment_reminders_for_tenant",
             ignore_result=True)
def send_payment_reminders_for_tenant(self, schema_name: str):
    """
    Send STK Push reminders for unpaid invoices that are due today or 1 day away.
    Avoids re-sending if a push was already sent in the last 12 hours.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .models import Invoice
            today = date.today()
            tomorrow = today + timedelta(days=1)

            due_invoices = Invoice.objects.filter(
                status=Invoice.Status.UNPAID,
                due_date__in=[today, tomorrow],
            ).select_related("subscription__subscriber")

            for invoice in due_invoices:
                logger.info(
                    "Reminder STK Push: invoice=%s subscriber=%s",
                    invoice.reference,
                    invoice.subscription.subscriber.full_name,
                )
                send_stk_push_for_invoice.delay(schema_name, invoice.pk)

    except Exception as exc:
        logger.exception(
            "send_payment_reminders_for_tenant failed (%s): %s", schema_name, exc
        )
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ─────────────────────────────────────────────────────────────────────────────
# OVERDUE DETECTION & AUTO-SUSPEND
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, name="subscribers.check_overdue_for_all_tenants",
             ignore_result=True)
def check_overdue_for_all_tenants(self):
    """Daily overdue check across all tenants."""
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        for tenant in TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        ):
            check_overdue_for_tenant.delay(tenant.schema_name)
    except Exception as exc:
        logger.exception("check_overdue_for_all_tenants: %s", exc)
        raise self.retry(exc=exc, countdown=300, max_retries=2)


@shared_task(bind=True, name="subscribers.check_overdue_for_tenant",
             ignore_result=True)
def check_overdue_for_tenant(self, schema_name: str):
    """
    1. Mark UNPAID invoices past their due date as OVERDUE.
    2. Auto-suspend subscribers who are past grace period.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from .models import Invoice, Subscription, Subscriber
            from .radius_service import suspend_subscriber
            today = date.today()

            # ── Step 1: Mark overdue ─────────────────────────────────────
            newly_overdue = Invoice.objects.filter(
                status=Invoice.Status.UNPAID,
                due_date__lt=today,
            )
            count = newly_overdue.update(status=Invoice.Status.OVERDUE)
            if count:
                logger.info(
                    "%d invoices marked OVERDUE in %s", count, schema_name
                )

            # ── Step 2: Auto-suspend past grace period ───────────────────
            # select_for_update() prevents the payment callback task from
            # reading a stale ACTIVE status while we are in the process of
            # suspending. Both tasks lock the Subscription row; whichever
            # acquires the lock first wins, the other sees the updated status.
            overdue_invoices = Invoice.objects.filter(
                status=Invoice.Status.OVERDUE,
                subscription__status=Subscription.Status.ACTIVE,
            ).select_related(
                "subscription__subscriber",
                "subscription__plan",
            )

            for invoice in overdue_invoices:
                sub = invoice.subscription
                grace_deadline = invoice.due_date + timedelta(
                    days=sub.plan.grace_days
                )
                if today > grace_deadline:
                    with transaction.atomic():
                        # Re-read inside a lock — bail if already suspended
                        # (payment callback may have beaten us)
                        locked_sub = Subscription.objects.select_for_update().get(
                            pk=sub.pk
                        )
                        if locked_sub.status != Subscription.Status.ACTIVE:
                            logger.info(
                                "Skipping suspend for %s — status already %s",
                                sub.subscriber.full_name, locked_sub.status,
                            )
                            continue

                        # Also check invoice inside lock — if it got paid, skip
                        locked_inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
                        if locked_inv.status == Invoice.Status.PAID:
                            logger.info(
                                "Skipping suspend for %s — invoice paid",
                                sub.subscriber.full_name,
                            )
                            continue

                        locked_sub.status = Subscription.Status.SUSPENDED
                        locked_sub.suspended_at = timezone.now()
                        locked_sub.suspension_reason = "Non-payment"
                        locked_sub.save(update_fields=[
                            "status", "suspended_at", "suspension_reason", "updated_at"
                        ])

                        subscriber = locked_sub.subscriber
                        Subscriber.objects.filter(pk=subscriber.pk).update(
                            status=Subscriber.Status.SUSPENDED
                        )

                    # RADIUS call outside the transaction
                    try:
                        suspend_subscriber(locked_sub, reason="non-payment")
                        logger.info(
                            "Auto-suspended %s (invoice %s overdue by %d days)",
                            subscriber.full_name,
                            invoice.reference,
                            (today - invoice.due_date).days,
                        )
                    except Exception as radius_exc:
                        logger.error(
                            "RADIUS suspend failed for %s: %s",
                            subscriber.pppoe_username, radius_exc,
                        )

    except Exception as exc:
        logger.exception(
            "check_overdue_for_tenant failed (%s): %s", schema_name, exc
        )
        raise self.retry(exc=exc, countdown=60, max_retries=2)
