"""
Billing views — payment history, STK Push initiation, and M-Pesa callback.
All staff views require login and run inside tenant schema.
The callback endpoint is public (called by Safaricom Daraja servers).
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView

from .models import Payment
from .mpesa import MpesaNotConfigured, MpesaApiError, parse_callback

logger = logging.getLogger(__name__)


# ── Payment list ──────────────────────────────────────────────────────────────

class PaymentListView(LoginRequiredMixin, ListView):
    model = Payment
    template_name = "billing/index.html"
    context_object_name = "payments"
    paginate_by = 30

    def get_queryset(self):
        qs = Payment.objects.all()

        status = self.request.GET.get("status", "").strip()
        if status in Payment.Status.values:
            qs = qs.filter(status=status)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(phone_number__icontains=q) |
                Q(mpesa_receipt_number__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = Payment.Status.choices

        agg = Payment.objects.aggregate(
            total_count=Count("id"),
            completed_count=Count("id", filter=Q(status=Payment.Status.COMPLETED)),
            pending_count=Count("id", filter=Q(status=Payment.Status.PENDING)),
            failed_count=Count("id", filter=Q(status=Payment.Status.FAILED)),
            total_revenue=Sum(
                "amount_kes", filter=Q(status=Payment.Status.COMPLETED)
            ),
        )
        ctx["total_count"] = agg["total_count"]
        ctx["completed_count"] = agg["completed_count"]
        ctx["pending_count"] = agg["pending_count"]
        ctx["failed_count"] = agg["failed_count"]
        ctx["total_revenue"] = agg["total_revenue"] or 0
        return ctx


# ── STK Push initiation (staff) ───────────────────────────────────────────────

class StkPushView(LoginRequiredMixin, View):
    """
    Staff-facing view to manually trigger an M-Pesa STK Push.
    GET  → renders the form (billing/stk_push.html)
    POST → initiates the push and redirects back with a flash message.

    This is used for:
      - Testing the Daraja integration from the portal
      - Manually collecting a payment from a walk-in customer
    """
    template_name = "billing/stk_push.html"

    def get(self, request):
        from django.shortcuts import render
        from django.conf import settings
        return render(request, self.template_name, {
            "title": "Send STK Push",
            "mpesa_env": getattr(settings, "MPESA_ENVIRONMENT", "sandbox"),
            "mpesa_shortcode": getattr(settings, "MPESA_SHORTCODE", "174379"),
        })

    def post(self, request):
        from django.shortcuts import render, redirect
        import uuid

        phone = request.POST.get("phone_number", "").strip()
        amount_raw = request.POST.get("amount", "").strip()
        description = request.POST.get("description", "Manual payment").strip()

        # ── Basic validation ──────────────────────────────────────────────
        errors = {}
        if not phone:
            errors["phone_number"] = "Phone number is required."
        elif not (phone.startswith("2547") or phone.startswith("2541")) or len(phone) != 12:
            errors["phone_number"] = (
                "Enter phone in 2547XXXXXXXX format (12 digits, starts with 2547 or 2541)."
            )
        if not amount_raw:
            errors["amount"] = "Amount is required."
        else:
            try:
                amount = int(float(amount_raw))
                if amount < 1:
                    errors["amount"] = "Amount must be at least KES 1."
            except ValueError:
                errors["amount"] = "Enter a valid number."

        if errors:
            return render(request, self.template_name, {
                "title": "Send STK Push",
                "errors": errors,
                "form_data": request.POST,
            })

        # ── Create a pending Payment record ───────────────────────────────
        reference = uuid.uuid4()
        payment = Payment.objects.create(
            reference=reference,
            phone_number=phone,
            amount_kes=amount,
            status=Payment.Status.PENDING,
        )

        # ── Fire STK Push ─────────────────────────────────────────────────
        try:
            from .mpesa import stk_push
            result = stk_push(
                phone=phone,
                amount=amount,
                account_ref=str(reference)[:12].upper(),
                description=description[:13],
                callback_path="/billing/mpesa/callback/",
            )
            checkout_id = result["CheckoutRequestID"]
            payment.mpesa_checkout_request_id = checkout_id
            payment.save(update_fields=["mpesa_checkout_request_id", "updated_at"])

            messages.success(
                request,
                f"STK Push sent to {phone} for KES {amount}. "
                f"Customer will receive a prompt on their phone. "
                f"Checkout ID: {checkout_id}",
            )
            logger.info(
                "Manual STK Push: phone=%s amount=%s checkout_id=%s user=%s",
                phone, amount, checkout_id, request.user.email,
            )

        except MpesaNotConfigured as exc:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            messages.error(
                request,
                "M-Pesa is not configured. Contact the system administrator. "
                f"Detail: {exc}",
            )
            logger.error("STK Push: MpesaNotConfigured — %s", exc)

        except MpesaApiError as exc:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            messages.error(
                request,
                f"Daraja API error: {exc}. Check your credentials and try again.",
            )
            logger.error("STK Push: MpesaApiError — %s", exc)

        from django.urls import reverse
        return redirect(reverse("billing:index"))


# ── M-Pesa Daraja callback (public, no CSRF) ──────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class MpesaCallbackView(View):
    """
    Receives the async STK Push result callback from Safaricom Daraja.

    This Django endpoint is an alternative callback target for payments
    initiated directly from the staff portal (StkPushView above).
    The captive portal FastAPI service has its own /payments/callback.

    Must respond quickly — heavy work dispatched to Celery.
    Always returns ResultCode=0 to Daraja (even on errors), otherwise
    Safaricom will keep retrying.
    """

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, Exception) as exc:
            logger.error("M-Pesa callback: invalid JSON — %s", exc)
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        try:
            parsed = parse_callback(body)
        except (KeyError, ValueError) as exc:
            logger.error(
                "M-Pesa callback: malformed payload — %s\nbody=%s", exc, body
            )
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        checkout_id = parsed["checkout_request_id"]
        result_code = parsed["result_code"]
        receipt      = parsed.get("receipt_number") or ""
        phone        = parsed.get("phone_number") or ""
        amount       = parsed.get("amount") or 0

        logger.info(
            "M-Pesa Django callback: checkout_id=%s result_code=%s receipt=%s",
            checkout_id, result_code, receipt,
        )

        # Determine which tenant schema owns this checkout_request_id
        # by finding the matching billing_payment record across all schemas.
        schema_name = self._find_tenant_schema(checkout_id)

        if schema_name:
            # Dispatch to the portal voucher callback task
            try:
                from config.celery import app as celery_app
                celery_app.send_task(
                    "portal.process_voucher_payment_callback",
                    kwargs=dict(
                        schema_name=schema_name,
                        checkout_request_id=checkout_id,
                        result_code=result_code,
                        receipt_number=receipt,
                        phone_number=phone,
                        amount=amount,
                    ),
                )
                logger.info(
                    "Dispatched voucher callback task: tenant=%s checkout=%s",
                    schema_name, checkout_id,
                )
            except Exception as exc:
                logger.error("Failed to dispatch voucher callback task: %s", exc)
        else:
            # Try the subscriber invoice path
            inv_schema = self._find_invoice_tenant_schema(checkout_id)
            if inv_schema:
                try:
                    from config.celery import app as celery_app
                    celery_app.send_task(
                        "subscribers.process_invoice_payment_callback",
                        kwargs=dict(
                            schema_name=inv_schema,
                            checkout_request_id=checkout_id,
                            result_code=result_code,
                            receipt_number=receipt,
                            failure_reason=(
                                "" if result_code == 0
                                else parsed.get("result_desc", "")
                            ),
                        ),
                    )
                    logger.info(
                        "Dispatched invoice callback task: tenant=%s checkout=%s",
                        inv_schema, checkout_id,
                    )
                except Exception as exc:
                    logger.error("Failed to dispatch invoice callback task: %s", exc)
            else:
                logger.warning(
                    "M-Pesa callback: no tenant found for checkout_id=%s — dropped",
                    checkout_id,
                )

        # Always acknowledge Daraja immediately
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    # ── helpers ───────────────────────────────────────────────────────────

    def _find_tenant_schema(self, checkout_request_id: str):
        """
        Search billing_payment across all tenant schemas.
        Returns schema_name string or None.
        """
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            TenantModel = get_tenant_model()
            for tenant in TenantModel.objects.filter(is_active=True).exclude(
                schema_name="public"
            ):
                with schema_context(tenant.schema_name):
                    if Payment.objects.filter(
                        mpesa_checkout_request_id=checkout_request_id
                    ).exists():
                        return tenant.schema_name
        except Exception as exc:
            logger.exception("_find_tenant_schema error: %s", exc)
        return None

    def _find_invoice_tenant_schema(self, checkout_request_id: str):
        """
        Search subscribers_invoicepayment across all tenant schemas.
        Returns schema_name string or None.
        """
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            from apps.subscribers.models import InvoicePayment
            TenantModel = get_tenant_model()
            for tenant in TenantModel.objects.filter(is_active=True).exclude(
                schema_name="public"
            ):
                with schema_context(tenant.schema_name):
                    if InvoicePayment.objects.filter(
                        mpesa_checkout_request_id=checkout_request_id
                    ).exists():
                        return tenant.schema_name
        except Exception as exc:
            logger.exception("_find_invoice_tenant_schema error: %s", exc)
        return None
