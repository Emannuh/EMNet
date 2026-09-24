"""
Portal Celery tasks — voucher payment callback processing.

Called by the FastAPI captive portal after a Daraja M-Pesa callback arrives.
On success: creates an active Voucher and marks the Payment completed.
On failure: marks the Payment failed.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="portal.process_voucher_payment_callback",
             ignore_result=True)
def process_voucher_payment_callback(
    self,
    schema_name: str,
    checkout_request_id: str,
    result_code: int,
    receipt_number: str = "",
    phone_number: str = "",
    amount: float = 0,
):
    """
    Process the M-Pesa callback for a captive portal voucher purchase.

    On success (result_code == 0):
      - Finds the pending Payment by checkout_request_id
      - Marks it COMPLETED with the M-Pesa receipt number
      - Finds the VoucherPlan matching the payment amount
      - Creates an ACTIVE Voucher linked to the plan
      - Logs the event

    On failure (result_code != 0):
      - Marks the Payment FAILED

    The voucher is created here, not at STK Push initiation, so we
    never create a voucher for an unpaid request.
    """
    try:
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            from apps.billing.models import Payment
            from apps.portal.models import VoucherPlan, Voucher

            # Find the pending payment
            try:
                payment = Payment.objects.get(
                    mpesa_checkout_request_id=checkout_request_id,
                )
            except Payment.DoesNotExist:
                logger.warning(
                    "No Payment found for checkout_request_id=%s in %s",
                    checkout_request_id, schema_name,
                )
                return
            except Payment.MultipleObjectsReturned:
                payment = Payment.objects.filter(
                    mpesa_checkout_request_id=checkout_request_id,
                ).order_by("-created_at").first()

            if result_code == 0:
                # Mark payment complete
                payment.status = Payment.Status.COMPLETED
                payment.mpesa_receipt_number = receipt_number
                payment.save(update_fields=[
                    "status", "mpesa_receipt_number", "updated_at"
                ])

                # Find cheapest active plan matching the amount paid
                # (exact match first, then nearest equal-or-lower)
                plan = VoucherPlan.objects.filter(
                    is_active=True,
                    price_kes=payment.amount_kes,
                ).first()

                if not plan:
                    # Fall back to nearest plan at or below paid amount
                    plan = VoucherPlan.objects.filter(
                        is_active=True,
                        price_kes__lte=payment.amount_kes,
                    ).order_by("-price_kes").first()

                if not plan:
                    logger.error(
                        "No VoucherPlan found for amount KES %s in %s — "
                        "payment %s is complete but no voucher was created. "
                        "Manual intervention required.",
                        payment.amount_kes, schema_name, payment.reference,
                    )
                    return

                # Create the active voucher
                voucher = Voucher.objects.create(
                    plan=plan,
                    status=Voucher.Status.ACTIVE,
                    phone_number=phone_number or payment.phone_number,
                )

                # Link the payment to the voucher
                payment.voucher_id = voucher.pk
                payment.save(update_fields=["voucher_id", "updated_at"])

                logger.info(
                    "Voucher created after payment: schema=%s voucher=%s "
                    "plan=%s receipt=%s phone=%s",
                    schema_name, voucher.code, plan.name,
                    receipt_number, phone_number,
                )

            else:
                # Payment failed or was cancelled
                payment.status = Payment.Status.FAILED
                payment.failure_reason = f"M-Pesa result code {result_code}"
                payment.save(update_fields=[
                    "status", "failure_reason", "updated_at"
                ])
                logger.warning(
                    "Payment failed: schema=%s checkout=%s result_code=%s",
                    schema_name, checkout_request_id, result_code,
                )

    except Exception as exc:
        logger.exception(
            "process_voucher_payment_callback failed (%s, %s): %s",
            schema_name, checkout_request_id, exc,
        )
        raise self.retry(exc=exc, countdown=30, max_retries=3)
