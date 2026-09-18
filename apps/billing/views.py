"""
Billing views — payment history and stats for ISP staff.
All views require login; run inside tenant schema.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, Q
from django.views.generic import ListView

from .models import Payment


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
