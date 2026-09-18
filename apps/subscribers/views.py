"""
Subscriber management views.
Covers: service plans, IP pools, subscribers, subscriptions, invoices.
All views require login and run inside the tenant schema.
"""
import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView,
    TemplateView, View,
)

from .models import (
    ServicePlan, IpPool, IpAddress,
    Subscriber, Subscription, Invoice, InvoicePayment,
)
from .radius_service import (
    provision_subscriber, suspend_subscriber,
    reactivate_subscriber, deprovision_subscriber, update_speed,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

class SubscriberDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "subscribers/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_subscribers"] = Subscriber.objects.count()
        ctx["active_subscribers"] = Subscriber.objects.filter(
            status=Subscriber.Status.ACTIVE).count()
        ctx["suspended_subscribers"] = Subscriber.objects.filter(
            status=Subscriber.Status.SUSPENDED).count()
        ctx["pending_subscribers"] = Subscriber.objects.filter(
            status=Subscriber.Status.PENDING).count()

        billing = Invoice.objects.aggregate(
            total_revenue=Sum("amount_kes", filter=Q(status=Invoice.Status.PAID)),
            unpaid_count=Count("id", filter=Q(status=Invoice.Status.UNPAID)),
            overdue_count=Count("id", filter=Q(status=Invoice.Status.OVERDUE)),
        )
        ctx["total_revenue"] = billing["total_revenue"] or 0
        ctx["unpaid_invoices"] = billing["unpaid_count"]
        ctx["overdue_invoices"] = billing["overdue_count"]

        # Recent subscribers
        ctx["recent_subscribers"] = Subscriber.objects.order_by(
            "-created_at")[:5]
        # Overdue invoices for alert panel
        ctx["overdue_list"] = Invoice.objects.filter(
            status=Invoice.Status.OVERDUE
        ).select_related(
            "subscription__subscriber"
        ).order_by("due_date")[:10]
        return ctx


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE PLANS
# ─────────────────────────────────────────────────────────────────────────────

class ServicePlanListView(LoginRequiredMixin, ListView):
    model = ServicePlan
    template_name = "subscribers/plan_list.html"
    context_object_name = "plans"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = ServicePlan.objects.count()
        ctx["active"] = ServicePlan.objects.filter(is_active=True).count()
        return ctx


class ServicePlanCreateView(LoginRequiredMixin, CreateView):
    model = ServicePlan
    template_name = "subscribers/plan_form.html"
    fields = [
        "name", "description", "connection_type",
        "download_mbps", "upload_mbps",
        "price_kes", "billing_cycle", "grace_days", "is_active",
    ]
    success_url = reverse_lazy("subscribers:plan_list")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{form.instance.name}" created.')
        return super().form_valid(form)


class ServicePlanUpdateView(LoginRequiredMixin, UpdateView):
    model = ServicePlan
    template_name = "subscribers/plan_form.html"
    fields = [
        "name", "description", "connection_type",
        "download_mbps", "upload_mbps",
        "price_kes", "billing_cycle", "grace_days", "is_active",
    ]
    success_url = reverse_lazy("subscribers:plan_list")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{form.instance.name}" updated.')
        return super().form_valid(form)


class ServicePlanDeleteView(LoginRequiredMixin, DeleteView):
    model = ServicePlan
    template_name = "subscribers/plan_confirm_delete.html"
    success_url = reverse_lazy("subscribers:plan_list")

    def form_valid(self, form):
        messages.success(self.request, f'Plan "{self.object.name}" deleted.')
        return super().form_valid(form)


# ─────────────────────────────────────────────────────────────────────────────
# IP POOLS
# ─────────────────────────────────────────────────────────────────────────────

class IpPoolListView(LoginRequiredMixin, ListView):
    model = IpPool
    template_name = "subscribers/ippool_list.html"
    context_object_name = "pools"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for pool in ctx["pools"]:
            pool.available_count = pool.assigned_ips.filter(
                status=IpAddress.Status.AVAILABLE).count()
        return ctx


class IpPoolCreateView(LoginRequiredMixin, CreateView):
    model = IpPool
    template_name = "subscribers/ippool_form.html"
    fields = ["name", "network", "gateway", "dns_primary", "dns_secondary",
              "description", "is_active"]
    success_url = reverse_lazy("subscribers:ippool_list")

    def form_valid(self, form):
        messages.success(self.request, f'IP Pool "{form.instance.name}" created.')
        return super().form_valid(form)


class IpPoolUpdateView(LoginRequiredMixin, UpdateView):
    model = IpPool
    template_name = "subscribers/ippool_form.html"
    fields = ["name", "network", "gateway", "dns_primary", "dns_secondary",
              "description", "is_active"]
    success_url = reverse_lazy("subscribers:ippool_list")

    def form_valid(self, form):
        messages.success(self.request, f'IP Pool "{form.instance.name}" updated.')
        return super().form_valid(form)


class IpAddressCreateView(LoginRequiredMixin, View):
    """Add a single IP address to a pool."""

    def post(self, request, pool_pk):
        pool = get_object_or_404(IpPool, pk=pool_pk)
        address = request.POST.get("address", "").strip()
        if address:
            IpAddress.objects.get_or_create(
                pool=pool, address=address,
                defaults={"status": IpAddress.Status.AVAILABLE},
            )
            messages.success(request, f"{address} added to {pool.name}.")
        return redirect("subscribers:ippool_list")


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIBERS
# ─────────────────────────────────────────────────────────────────────────────

class SubscriberListView(LoginRequiredMixin, ListView):
    model = Subscriber
    template_name = "subscribers/subscriber_list.html"
    context_object_name = "subscribers"
    paginate_by = 25

    def get_queryset(self):
        qs = Subscriber.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) |
                Q(phone__icontains=q) |
                Q(pppoe_username__icontains=q)
            )
        status = self.request.GET.get("status", "")
        if status in Subscriber.Status.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = Subscriber.Status.choices
        ctx["total"] = Subscriber.objects.count()
        ctx["active"] = Subscriber.objects.filter(
            status=Subscriber.Status.ACTIVE).count()
        ctx["suspended"] = Subscriber.objects.filter(
            status=Subscriber.Status.SUSPENDED).count()
        return ctx


class SubscriberDetailView(LoginRequiredMixin, DetailView):
    model = Subscriber
    template_name = "subscribers/subscriber_detail.html"
    context_object_name = "subscriber"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subscriptions"] = self.object.subscriptions.select_related(
            "plan", "assigned_ip"
        ).order_by("-created_at")
        ctx["invoices"] = Invoice.objects.filter(
            subscription__subscriber=self.object
        ).order_by("-created_at")[:10]
        ctx["active_sub"] = self.object.active_subscription
        ctx["plans"] = ServicePlan.objects.filter(is_active=True)
        return ctx


class SubscriberCreateView(LoginRequiredMixin, CreateView):
    model = Subscriber
    template_name = "subscribers/subscriber_form.html"
    fields = [
        "full_name", "email", "phone", "id_number",
        "address", "gps_lat", "gps_lng",
        "cpe_serial", "cpe_mac",
        "pppoe_username", "pppoe_password",
        "notes",
    ]

    def get_success_url(self):
        return reverse("subscribers:subscriber_detail",
                       kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plans"] = ServicePlan.objects.filter(is_active=True)
        ctx["ip_pools"] = IpPool.objects.filter(is_active=True)
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        subscriber = form.save(commit=False)
        subscriber.status = Subscriber.Status.PENDING
        subscriber.save()

        # Optionally create subscription immediately
        plan_id = self.request.POST.get("plan_id")
        if plan_id:
            try:
                plan = ServicePlan.objects.get(pk=plan_id, is_active=True)
                ip_pool_id = self.request.POST.get("ip_pool_id")
                assigned_ip = None

                if ip_pool_id and plan.connection_type in [
                    ServicePlan.ConnectionType.STATIC_IP,
                    ServicePlan.ConnectionType.DHCP_MAC,
                ]:
                    assigned_ip = IpAddress.objects.filter(
                        pool_id=ip_pool_id,
                        status=IpAddress.Status.AVAILABLE,
                    ).first()
                    if assigned_ip:
                        assigned_ip.status = IpAddress.Status.ASSIGNED
                        assigned_ip.save(update_fields=["status"])

                sub = Subscription.objects.create(
                    subscriber=subscriber,
                    plan=plan,
                    assigned_ip=assigned_ip,
                    status=Subscription.Status.ACTIVE,
                    start_date=date.today(),
                    next_due_date=plan.next_due_date(date.today()),
                )

                subscriber.status = Subscriber.Status.ACTIVE
                subscriber.save(update_fields=["status", "updated_at"])

                # Write RADIUS credentials
                provision_subscriber(sub)
                messages.success(
                    self.request,
                    f'Subscriber "{subscriber.full_name}" created and provisioned '
                    f'on plan "{plan.name}".',
                )
            except ServicePlan.DoesNotExist:
                messages.warning(
                    self.request,
                    f'Subscriber created but plan not found. '
                    f'Assign a plan from the detail page.',
                )
        else:
            messages.success(
                self.request,
                f'Subscriber "{subscriber.full_name}" created. '
                f'Assign a plan to activate.',
            )
        return redirect(self.get_success_url())


class SubscriberUpdateView(LoginRequiredMixin, UpdateView):
    model = Subscriber
    template_name = "subscribers/subscriber_form.html"
    fields = [
        "full_name", "email", "phone", "id_number",
        "address", "gps_lat", "gps_lng",
        "cpe_serial", "cpe_mac",
        "pppoe_username", "pppoe_password",
        "notes",
    ]

    def get_success_url(self):
        return reverse("subscribers:subscriber_detail",
                       kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Subscriber "{form.instance.full_name}" updated.',
        )
        return super().form_valid(form)


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

class SubscriptionAssignView(LoginRequiredMixin, View):
    """Assign a service plan to a subscriber (creates a new Subscription)."""

    @transaction.atomic
    def post(self, request, subscriber_pk):
        subscriber = get_object_or_404(Subscriber, pk=subscriber_pk)
        plan_id = request.POST.get("plan_id")
        ip_pool_id = request.POST.get("ip_pool_id")

        if not plan_id:
            messages.error(request, "Please select a plan.")
            return redirect("subscribers:subscriber_detail",
                            pk=subscriber_pk)

        plan = get_object_or_404(ServicePlan, pk=plan_id, is_active=True)

        # Cancel any existing active subscription first
        existing = subscriber.subscriptions.filter(
            status=Subscription.Status.ACTIVE
        ).first()
        if existing:
            existing.status = Subscription.Status.CANCELLED
            existing.cancelled_at = timezone.now()
            existing.save(update_fields=[
                "status", "cancelled_at", "updated_at"
            ])
            deprovision_subscriber(existing)

        # Assign IP if needed
        assigned_ip = None
        if ip_pool_id and plan.connection_type in [
            ServicePlan.ConnectionType.STATIC_IP,
            ServicePlan.ConnectionType.DHCP_MAC,
        ]:
            assigned_ip = IpAddress.objects.filter(
                pool_id=ip_pool_id,
                status=IpAddress.Status.AVAILABLE,
            ).first()
            if assigned_ip:
                assigned_ip.status = IpAddress.Status.ASSIGNED
                assigned_ip.save(update_fields=["status"])

        sub = Subscription.objects.create(
            subscriber=subscriber,
            plan=plan,
            assigned_ip=assigned_ip,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            next_due_date=plan.next_due_date(date.today()),
        )

        subscriber.status = Subscriber.Status.ACTIVE
        subscriber.save(update_fields=["status", "updated_at"])

        provision_subscriber(sub)
        messages.success(
            request,
            f'Plan "{plan.name}" assigned to {subscriber.full_name}.',
        )
        return redirect("subscribers:subscriber_detail", pk=subscriber_pk)


class SubscriberSuspendView(LoginRequiredMixin, View):
    """Manually suspend a subscriber."""

    def post(self, request, pk):
        subscriber = get_object_or_404(Subscriber, pk=pk)
        reason = request.POST.get("reason", "Manual suspension by staff")
        sub = subscriber.active_subscription

        if sub:
            sub.status = Subscription.Status.SUSPENDED
            sub.suspended_at = timezone.now()
            sub.suspension_reason = reason
            sub.save(update_fields=[
                "status", "suspended_at", "suspension_reason", "updated_at"
            ])
            try:
                suspend_subscriber(sub, reason=reason)
            except Exception as e:
                logger.error("RADIUS suspend error: %s", e)

        subscriber.status = Subscriber.Status.SUSPENDED
        subscriber.save(update_fields=["status", "updated_at"])
        messages.warning(
            request,
            f'"{subscriber.full_name}" has been suspended.',
        )
        return redirect("subscribers:subscriber_detail", pk=pk)


class SubscriberReactivateView(LoginRequiredMixin, View):
    """Manually reactivate a suspended subscriber."""

    def post(self, request, pk):
        subscriber = get_object_or_404(Subscriber, pk=pk)
        sub = subscriber.subscriptions.filter(
            status=Subscription.Status.SUSPENDED
        ).first()

        if sub:
            sub.status = Subscription.Status.ACTIVE
            sub.suspended_at = None
            sub.suspension_reason = ""
            sub.save(update_fields=[
                "status", "suspended_at", "suspension_reason", "updated_at"
            ])
            try:
                reactivate_subscriber(sub)
            except Exception as e:
                logger.error("RADIUS reactivate error: %s", e)

        subscriber.status = Subscriber.Status.ACTIVE
        subscriber.save(update_fields=["status", "updated_at"])
        messages.success(
            request,
            f'"{subscriber.full_name}" has been reactivated.',
        )
        return redirect("subscribers:subscriber_detail", pk=pk)


class SubscriberCancelView(LoginRequiredMixin, View):
    """Cancel a subscriber's subscription and remove RADIUS credentials."""

    @transaction.atomic
    def post(self, request, pk):
        subscriber = get_object_or_404(Subscriber, pk=pk)
        sub = subscriber.active_subscription or subscriber.subscriptions.filter(
            status=Subscription.Status.SUSPENDED
        ).first()

        if sub:
            # Release assigned IP back to pool
            if sub.assigned_ip:
                sub.assigned_ip.status = IpAddress.Status.AVAILABLE
                sub.assigned_ip.save(update_fields=["status"])
                sub.assigned_ip = None
                sub.save(update_fields=["assigned_ip"])

            sub.status = Subscription.Status.CANCELLED
            sub.cancelled_at = timezone.now()
            sub.save(update_fields=[
                "status", "cancelled_at", "assigned_ip", "updated_at"
            ])
            try:
                deprovision_subscriber(sub)
            except Exception as e:
                logger.error("RADIUS deprovision error: %s", e)

        subscriber.status = Subscriber.Status.CANCELLED
        subscriber.save(update_fields=["status", "updated_at"])
        messages.info(
            request,
            f'"{subscriber.full_name}" subscription cancelled.',
        )
        return redirect("subscribers:subscriber_detail", pk=pk)


class PlanChangeView(LoginRequiredMixin, View):
    """Change the service plan on an active subscription."""

    @transaction.atomic
    def post(self, request, pk):
        subscriber = get_object_or_404(Subscriber, pk=pk)
        plan_id = request.POST.get("new_plan_id")
        sub = subscriber.active_subscription

        if not sub:
            messages.error(request, "No active subscription to change.")
            return redirect("subscribers:subscriber_detail", pk=pk)

        new_plan = get_object_or_404(ServicePlan, pk=plan_id, is_active=True)
        old_plan_name = sub.plan.name
        sub.plan = new_plan
        sub.save(update_fields=["plan", "updated_at"])

        try:
            update_speed(sub)
        except Exception as e:
            logger.error("RADIUS speed update error: %s", e)

        messages.success(
            request,
            f'Plan changed from "{old_plan_name}" to "{new_plan.name}".',
        )
        return redirect("subscribers:subscriber_detail", pk=pk)


# ─────────────────────────────────────────────────────────────────────────────
# INVOICES
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceListView(LoginRequiredMixin, ListView):
    model = Invoice
    template_name = "subscribers/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 30

    def get_queryset(self):
        qs = Invoice.objects.select_related(
            "subscription__subscriber", "subscription__plan"
        )
        status = self.request.GET.get("status", "")
        if status in Invoice.Status.values:
            qs = qs.filter(status=status)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                subscription__subscriber__full_name__icontains=q
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = Invoice.Status.choices
        agg = Invoice.objects.aggregate(
            unpaid=Count("id", filter=Q(status=Invoice.Status.UNPAID)),
            overdue=Count("id", filter=Q(status=Invoice.Status.OVERDUE)),
            paid=Count("id", filter=Q(status=Invoice.Status.PAID)),
            revenue=Sum("amount_kes", filter=Q(status=Invoice.Status.PAID)),
        )
        ctx.update({
            "unpaid_count": agg["unpaid"],
            "overdue_count": agg["overdue"],
            "paid_count": agg["paid"],
            "total_revenue": agg["revenue"] or 0,
        })
        return ctx


class InvoiceDetailView(LoginRequiredMixin, DetailView):
    model = Invoice
    template_name = "subscribers/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return Invoice.objects.select_related(
            "subscription__subscriber",
            "subscription__plan",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = self.object.payments.order_by("-created_at")
        return ctx


class InvoiceSendPaymentView(LoginRequiredMixin, View):
    """Manually trigger an STK Push for an unpaid invoice."""

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        if invoice.status == Invoice.Status.PAID:
            messages.info(request, "This invoice is already paid.")
            return redirect("subscribers:invoice_detail", pk=pk)

        from .tasks import send_stk_push_for_invoice
        from django_tenants.utils import get_tenant

        schema = get_tenant(request).schema_name
        send_stk_push_for_invoice.delay(schema, invoice.pk)

        messages.success(
            request,
            f"Payment request sent to "
            f"{invoice.subscription.subscriber.phone}.",
        )
        return redirect("subscribers:invoice_detail", pk=pk)


class InvoiceMarkPaidView(LoginRequiredMixin, View):
    """Manually mark an invoice as paid (for cash/bank transfer payments)."""

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        receipt = request.POST.get("receipt_number", "MANUAL").strip()

        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=["status", "updated_at"])

        InvoicePayment.objects.create(
            invoice=invoice,
            phone_number=invoice.subscription.subscriber.phone,
            amount_kes=invoice.amount_kes,
            mpesa_receipt_number=receipt,
            status=InvoicePayment.Status.COMPLETED,
        )

        # Reactivate if suspended
        sub = invoice.subscription
        if sub.status == Subscription.Status.SUSPENDED:
            sub.status = Subscription.Status.ACTIVE
            sub.suspended_at = None
            sub.suspension_reason = ""
            sub.save(update_fields=[
                "status", "suspended_at", "suspension_reason", "updated_at"
            ])
            subscriber = sub.subscriber
            subscriber.status = Subscriber.Status.ACTIVE
            subscriber.save(update_fields=["status", "updated_at"])
            try:
                reactivate_subscriber(sub)
            except Exception as e:
                logger.error("RADIUS reactivate error on manual pay: %s", e)

        messages.success(
            request,
            f"Invoice marked as paid. Receipt: {receipt}",
        )
        return redirect("subscribers:invoice_detail", pk=pk)
