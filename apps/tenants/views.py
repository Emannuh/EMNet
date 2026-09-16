"""
Tenant management views — super-admin only.
All views run in the public schema.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, UpdateView, View
from django.views.generic.edit import FormView

from .forms import TenantOnboardingForm, TenantEditForm
from .models import Tenant, Domain

User = get_user_model()


class SuperAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restricts access to SUPER_ADMIN role users only."""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_super_admin


# ── Tenant list ───────────────────────────────────────────────────────────────

class TenantListView(SuperAdminRequiredMixin, ListView):
    model = Tenant
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 20

    def get_queryset(self):
        qs = Tenant.objects.order_by("-created_at")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["total"] = Tenant.objects.count()
        ctx["active"] = Tenant.objects.filter(is_active=True).count()
        return ctx


# ── Tenant onboarding ─────────────────────────────────────────────────────────

class TenantCreateView(SuperAdminRequiredMixin, FormView):
    template_name = "tenants/tenant_create.html"
    form_class = TenantOnboardingForm
    success_url = reverse_lazy("tenants:list")

    @transaction.atomic
    def form_valid(self, form):
        cd = form.cleaned_data

        # 1. Create the Tenant (auto-creates Postgres schema via django-tenants)
        tenant = Tenant(
            schema_name=cd["schema_name"],
            name=cd["name"],
            contact_email=cd["contact_email"],
            contact_phone=cd.get("contact_phone", ""),
        )
        tenant.save()  # triggers schema creation

        # 2. Create primary domain  (schema_name.localhost for dev)
        Domain.objects.create(
            domain=f"{cd['schema_name']}.localhost",
            tenant=tenant,
            is_primary=True,
        )

        # 3. Create the ISP admin user in the PUBLIC schema
        #    (tenant-scoped users will be added later inside the tenant schema)
        User.objects.create_user(
            email=cd["admin_email"],
            password=cd["admin_password"],
            full_name=cd["admin_full_name"],
            role=User.Role.ISP_ADMIN,
        )

        messages.success(
            self.request,
            f'Tenant "{tenant.name}" created successfully. '
            f'Admin login: {cd["admin_email"]}',
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


# ── Tenant detail ─────────────────────────────────────────────────────────────

class TenantDetailView(SuperAdminRequiredMixin, DetailView):
    model = Tenant
    template_name = "tenants/tenant_detail.html"
    context_object_name = "tenant"
    slug_field = "schema_name"
    slug_url_kwarg = "schema_name"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["domains"] = self.object.domains.all()
        ctx["edit_form"] = TenantEditForm(instance=self.object)
        return ctx


# ── Tenant edit ───────────────────────────────────────────────────────────────

class TenantUpdateView(SuperAdminRequiredMixin, UpdateView):
    model = Tenant
    form_class = TenantEditForm
    template_name = "tenants/tenant_detail.html"
    slug_field = "schema_name"
    slug_url_kwarg = "schema_name"

    def get_success_url(self):
        return reverse_lazy("tenants:detail", kwargs={"schema_name": self.object.schema_name})

    def form_valid(self, form):
        messages.success(self.request, "Tenant updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


# ── Tenant deactivate/activate (HTMX-friendly toggle) ────────────────────────

class TenantToggleActiveView(SuperAdminRequiredMixin, View):
    def post(self, request, schema_name):
        tenant = get_object_or_404(Tenant, schema_name=schema_name)
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active", "updated_at"])
        status = "activated" if tenant.is_active else "deactivated"
        messages.success(request, f'Tenant "{tenant.name}" {status}.')
        # HTMX: return to detail page; full-page requests redirect to list
        if request.htmx:
            from django.template.loader import render_to_string
            from django.http import HttpResponse
            badge = render_to_string(
                "tenants/_status_badge.html", {"tenant": tenant}, request=request
            )
            return HttpResponse(badge)
        return redirect("tenants:detail", schema_name=schema_name)
