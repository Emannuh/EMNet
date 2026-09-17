"""
Portal admin views — voucher plan management, voucher list, WiFi sessions.
All views require login; run inside tenant schema.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import VoucherPlan, Voucher, WifiSession


# ── Voucher Plans ─────────────────────────────────────────────────────────────

class VoucherPlanListView(LoginRequiredMixin, ListView):
    model = VoucherPlan
    template_name = "portal/index.html"
    context_object_name = "plans"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_plans"] = VoucherPlan.objects.count()
        ctx["active_plans"] = VoucherPlan.objects.filter(is_active=True).count()
        ctx["total_vouchers"] = Voucher.objects.count()
        ctx["active_vouchers"] = Voucher.objects.filter(status=Voucher.Status.ACTIVE).count()
        ctx["total_sessions"] = WifiSession.objects.count()
        return ctx


class VoucherPlanCreateView(LoginRequiredMixin, CreateView):
    model = VoucherPlan
    template_name = "portal/plan_form.html"
    fields = ["name", "duration_minutes", "data_mb", "price_kes", "is_active"]
    success_url = reverse_lazy("portal:index")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{form.instance.name}" created.')
        return super().form_valid(form)


class VoucherPlanUpdateView(LoginRequiredMixin, UpdateView):
    model = VoucherPlan
    template_name = "portal/plan_form.html"
    fields = ["name", "duration_minutes", "data_mb", "price_kes", "is_active"]
    success_url = reverse_lazy("portal:index")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{form.instance.name}" updated.')
        return super().form_valid(form)


class VoucherPlanDeleteView(LoginRequiredMixin, DeleteView):
    model = VoucherPlan
    template_name = "portal/plan_confirm_delete.html"
    success_url = reverse_lazy("portal:index")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{self.object.name}" deleted.')
        return super().form_valid(form)


# ── Vouchers ──────────────────────────────────────────────────────────────────

class VoucherListView(LoginRequiredMixin, ListView):
    model = Voucher
    template_name = "portal/voucher_list.html"
    context_object_name = "vouchers"
    paginate_by = 30

    def get_queryset(self):
        qs = Voucher.objects.select_related("plan")
        status = self.request.GET.get("status", "")
        if status in Voucher.Status.values:
            qs = qs.filter(status=status)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(phone_number__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = Voucher.Status.choices
        return ctx


# ── WiFi Sessions ─────────────────────────────────────────────────────────────

class WifiSessionListView(LoginRequiredMixin, ListView):
    model = WifiSession
    template_name = "portal/session_list.html"
    context_object_name = "sessions"
    paginate_by = 30

    def get_queryset(self):
        return WifiSession.objects.select_related("voucher__plan")
