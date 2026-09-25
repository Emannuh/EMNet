"""
Billing Celery tasks.

Tasks
------
poll_pending_payments          — every 2 minutes: query Daraja for stuck
                                 pending billing_payment records and resolve them.
poll_pending_invoice_payments  — every 2 minutes: same for InvoicePayment records.

These are the fallback for when Daraja's callback never arrives (network
timeout, DNS failure, etc.).  They call query_stk_status() and then
dispatch the same callback-processing tasks that the live callback uses,
so all downstream logic (voucher creation, invoice marking paid, RADIUS
reactivation) runs identically regardless of which path triggers it.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)

# How old (in minutes) a pending payment must be before we query its status.
# Too short = we'll query before Daraja has even processed it.
# 3 minutes is safe — Daraja typically resolves within 60 seconds.
PENDING_MIN_AGE_MINUTES = 3

# Maximum age (in minutes) — don't bother querying very old stale records.
PENDING_MAX_AGE_MINUTES = 60


# ── Voucher / billing_payment fallback ───────────────────────────────────────

@shared_task(bind=True, name="billing.poll_pending_payments", ignore_result=True)
def poll_pending_payments(self):
    """
    Entry point: iterate all tenant schemas and poll pending billing_payment
    records whose checkout_request_id has not been resolved by a callback.
    """
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        )
        for tenant in tenants:
            poll_pending_payments_for_tenant.delay(tenant.schema_name)
    except Exception as exc:
        logger.exception("poll_pending_payments failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@shared_task(bind=True, name="billing.poll_pending_payments_for_tenant",
             ignore_result=True)
def poll_pending_payments_for_tenant(self, schema_name: str):
    """
    For a single tenant: find billing_payment records that are still
    pending and old enough to warrant a Daraja status query.
    """
    try:
        from django_tenants.utils import schema_context
        from django.utils import timezone
        from datetime import timedelta

        with schema_context(schema_name):
            from .models import Payment

            now = timezone.now()
            min_age = now - timedelta(minutes=PENDING_MIN_AGE_MINUTES)
            max_age = now - timedelta(minutes=PENDING_MAX_AGE_MINUTES)

            stuck = Payment.objects.filter(
                status=Payment.Status.PENDING,
                mpesa_checkout_request_id__gt="",  # must have a checkout ID
                created_at__lt=min_age,
                created_at__gt=max_age,
            ).values_list("mpesa_checkout_request_id", flat=True)

            for checkout_id in stuck:
                poll_single_payment.delay(schema_name, checkout_id)

    except Exception as exc:
        logger.exception(
            "poll_pending_payments_for_tenant failed (%s): %s", schema_name, exc
        )
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@shared_task(bind=True, name="billing.poll_single_payment", ignore_result=True)
def poll_single_payment(self, schema_name: str, checkout_request_id: str):
    """
    Query Daraja for the status of a single stuck billing_payment.
    On resolution, dispatch portal.process_voucher_payment_callback.
    """
    try:
        from apps.billing.mpesa import (
            query_stk_status, MpesaNotConfigured, MpesaApiError
        )

        try:
            result = query_stk_status(checkout_request_id)
        except MpesaNotConfigured:
            logger.warning(
                "poll_single_payment: M-Pesa not configured — skipping %s",
                checkout_request_id,
            )
            return
        except MpesaApiError as exc:
            logger.error(
                "poll_single_payment: Daraja query error for %s: %s",
                checkout_request_id, exc,
            )
            raise self.retry(exc=exc, countdown=120, max_retries=2)

        result_code = int(result.get("ResultCode", -1))
        result_desc = result.get("ResultDesc", "")

        if result_code == 1032:
            # 1032 = request still being processed — check again later
            logger.debug(
                "poll_single_payment: %s still processing, will retry",
                checkout_request_id,
            )
            return

        logger.info(
            "poll_single_payment: resolved %s → ResultCode=%s",
            checkout_request_id, result_code,
        )

        # Dispatch the same Celery task the live callback uses
        from config.celery import app as celery_app
        celery_app.send_task(
            "portal.process_voucher_payment_callback",
            kwargs=dict(
                schema_name=schema_name,
                checkout_request_id=checkout_request_id,
                result_code=result_code,
                receipt_number="",   # not available via status query
                phone_number="",
                amount=0,
                failure_reason=result_desc if result_code != 0 else "",
            ),
        )

    except Exception as exc:
        logger.exception(
            "poll_single_payment failed (%s, %s): %s",
            schema_name, checkout_request_id, exc,
        )
        raise self.retry(exc=exc, countdown=120, max_retries=2)


# ── InvoicePayment fallback ───────────────────────────────────────────────────

@shared_task(bind=True, name="billing.poll_pending_invoice_payments",
             ignore_result=True)
def poll_pending_invoice_payments(self):
    """
    Entry point: iterate all tenant schemas and poll pending InvoicePayment
    records whose callback was never received.
    """
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.filter(is_active=True).exclude(
            schema_name="public"
        )
        for tenant in tenants:
            poll_pending_invoice_payments_for_tenant.delay(tenant.schema_name)
    except Exception as exc:
        logger.exception("poll_pending_invoice_payments failed: %s", exc)
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@shared_task(bind=True, name="billing.poll_pending_invoice_payments_for_tenant",
             ignore_result=True)
def poll_pending_invoice_payments_for_tenant(self, schema_name: str):
    """
    For a single tenant: find InvoicePayment records that are still pending
    and old enough to warrant a Daraja status query.
    """
    try:
        from django_tenants.utils import schema_context
        from django.utils import timezone
        from datetime import timedelta

        with schema_context(schema_name):
            from apps.subscribers.models import InvoicePayment

            now = timezone.now()
            min_age = now - timedelta(minutes=PENDING_MIN_AGE_MINUTES)
            max_age = now - timedelta(minutes=PENDING_MAX_AGE_MINUTES)

            stuck = InvoicePayment.objects.filter(
                status=InvoicePayment.Status.PENDING,
                mpesa_checkout_request_id__gt="",
                created_at__lt=min_age,
                created_at__gt=max_age,
            ).values_list("mpesa_checkout_request_id", flat=True)

            for checkout_id in stuck:
                poll_single_invoice_payment.delay(schema_name, checkout_id)

    except Exception as exc:
        logger.exception(
            "poll_pending_invoice_payments_for_tenant failed (%s): %s",
            schema_name, exc,
        )
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@shared_task(bind=True, name="billing.poll_single_invoice_payment",
             ignore_result=True)
def poll_single_invoice_payment(self, schema_name: str, checkout_request_id: str):
    """
    Query Daraja for a stuck InvoicePayment.
    On resolution, dispatch subscribers.process_invoice_payment_callback.
    """
    try:
        from apps.billing.mpesa import (
            query_stk_status, MpesaNotConfigured, MpesaApiError
        )

        try:
            result = query_stk_status(checkout_request_id)
        except MpesaNotConfigured:
            logger.warning(
                "poll_single_invoice_payment: M-Pesa not configured — skipping %s",
                checkout_request_id,
            )
            return
        except MpesaApiError as exc:
            logger.error(
                "poll_single_invoice_payment: Daraja error for %s: %s",
                checkout_request_id, exc,
            )
            raise self.retry(exc=exc, countdown=120, max_retries=2)

        result_code = int(result.get("ResultCode", -1))
        result_desc = result.get("ResultDesc", "")

        if result_code == 1032:
            logger.debug(
                "poll_single_invoice_payment: %s still processing",
                checkout_request_id,
            )
            return

        logger.info(
            "poll_single_invoice_payment: resolved %s → ResultCode=%s",
            checkout_request_id, result_code,
        )

        from config.celery import app as celery_app
        celery_app.send_task(
            "subscribers.process_invoice_payment_callback",
            kwargs=dict(
                schema_name=schema_name,
                checkout_request_id=checkout_request_id,
                result_code=result_code,
                receipt_number="",
                failure_reason=result_desc if result_code != 0 else "",
            ),
        )

    except Exception as exc:
        logger.exception(
            "poll_single_invoice_payment failed (%s, %s): %s",
            schema_name, checkout_request_id, exc,
        )
        raise self.retry(exc=exc, countdown=120, max_retries=2)
