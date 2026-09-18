"""
Accounts views — login, logout, and the main dashboard home.
"""
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        schema = getattr(self.request.tenant, "schema_name", "public")
        user = self.request.user
        if schema == "public":
            # Super-admin on public schema → tenant management
            if user.is_authenticated and user.is_super_admin:
                return reverse("tenants:list")
            # Any other role accidentally on public schema → same page,
            # they'll see the locked sidebar with a helpful message
            return reverse("tenants:list")
        # Tenant schema → ISP stats dashboard
        return reverse("accounts:dashboard")


class LogoutView(auth_views.LogoutView):
    pass


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    ISP stats dashboard — only reachable on a tenant schema.
    Public schema users are always redirected away before reaching here.
    """
    template_name = "accounts/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        schema = getattr(request.tenant, "schema_name", "public")
        if schema == "public":
            user = request.user
            if user.is_authenticated and user.is_super_admin:
                return redirect("tenants:list")
            # Non-super-admin on public schema — show a clear message
            return redirect("accounts:public_landing")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # ── Network stats ─────────────────────────────────────────────────
        try:
            from apps.network.models import Device
            net = Device.objects.aggregate(
                total=Count("id"),
                up=Count("id", filter=Q(status="up")),
                down=Count("id", filter=Q(status="down")),
                unknown=Count("id", filter=Q(status="unknown")),
            )
            ctx["net_total"] = net["total"]
            ctx["net_up"] = net["up"]
            ctx["net_down"] = net["down"]
            ctx["net_unknown"] = net["unknown"]
        except Exception:
            ctx["net_total"] = ctx["net_up"] = ctx["net_down"] = ctx["net_unknown"] = 0

        # ── Portal stats ──────────────────────────────────────────────────
        try:
            from apps.portal.models import Voucher, WifiSession
            ctx["vouchers_active"] = Voucher.objects.filter(status="active").count()
            ctx["vouchers_total"] = Voucher.objects.count()
            ctx["sessions_live"] = WifiSession.objects.filter(
                ended_at__isnull=True).count()
            ctx["sessions_total"] = WifiSession.objects.count()
        except Exception:
            ctx["vouchers_active"] = ctx["vouchers_total"] = 0
            ctx["sessions_live"] = ctx["sessions_total"] = 0

        # ── Billing stats ─────────────────────────────────────────────────
        try:
            from apps.billing.models import Payment
            billing = Payment.objects.aggregate(
                total_revenue=Sum("amount_kes", filter=Q(status="completed")),
                completed=Count("id", filter=Q(status="completed")),
                pending=Count("id", filter=Q(status="pending")),
            )
            ctx["revenue"] = billing["total_revenue"] or 0
            ctx["payments_completed"] = billing["completed"]
            ctx["payments_pending"] = billing["pending"]
        except Exception:
            ctx["revenue"] = 0
            ctx["payments_completed"] = ctx["payments_pending"] = 0

        # ── Subscriber stats ──────────────────────────────────────────────
        try:
            from apps.subscribers.models import Subscriber, Invoice
            ctx["subscribers_active"] = Subscriber.objects.filter(
                status="active").count()
            ctx["subscribers_total"] = Subscriber.objects.count()
            ctx["invoices_overdue"] = Invoice.objects.filter(
                status="overdue").count()
        except Exception:
            ctx["subscribers_active"] = ctx["subscribers_total"] = 0
            ctx["invoices_overdue"] = 0

        return ctx


class PublicLandingView(TemplateView):
    """
    Shown to non-super-admin users who land on the public schema.
    Tells them to use their ISP's subdomain URL.
    """
    template_name = "accounts/public_landing.html"
