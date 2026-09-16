from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ["name", "schema_name", "contact_email", "is_active", "created_at"]
    search_fields = ["name", "schema_name", "contact_email"]
    list_filter = ["is_active"]


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["domain", "tenant", "is_primary"]
