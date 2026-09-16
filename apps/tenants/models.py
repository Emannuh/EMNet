"""
Tenant and Domain models required by django-tenants.
Every ISP gets its own Postgres schema.
"""
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    """Represents a single ISP subscriber on the platform."""

    name = models.CharField(max_length=200)
    # Contact details
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30, blank=True)
    # Subscription
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # django-tenants: auto-create the schema on save
    auto_create_schema = True

    class Meta:
        verbose_name = "Tenant (ISP)"
        verbose_name_plural = "Tenants (ISPs)"

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """Maps a hostname/subdomain to a Tenant."""

    class Meta:
        verbose_name = "Domain"
        verbose_name_plural = "Domains"
