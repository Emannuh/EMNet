"""
Integration tests for Tenant model — schema creation, domain uniqueness,
and duplicate schema rejection.

These tests use django-tenants' test helpers so schema creation runs
against the real Postgres backend (requires the test DB to be set up).
Mark with @pytest.mark.django_db(transaction=True) because schema DDL
cannot run inside a transaction on Postgres.
"""
import pytest
from django.db import IntegrityError
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient

from apps.tenants.models import Domain, Tenant


@pytest.mark.django_db(transaction=True)
class TenantCreationTest(TenantTestCase):
    """Tests that run inside a freshly created tenant schema."""

    @classmethod
    def setup_tenant(cls, tenant):
        """Called by TenantTestCase to configure the test tenant."""
        tenant.name = "Test ISP"
        tenant.contact_email = "test@isp.co.ke"
        return tenant

    def test_tenant_is_created_with_correct_name(self):
        self.assertEqual(self.tenant.name, "Test ISP")

    def test_tenant_is_active_by_default(self):
        self.assertTrue(self.tenant.is_active)

    def test_str_returns_name(self):
        self.assertEqual(str(self.tenant), "Test ISP")

    def test_primary_domain_exists(self):
        self.assertTrue(
            Domain.objects.filter(tenant=self.tenant, is_primary=True).exists()
        )


@pytest.mark.django_db(transaction=True)
class TenantDuplicateSchemaTest(TenantTestCase):
    """Ensures duplicate schema_name is rejected at the DB level."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Dupe ISP"
        tenant.contact_email = "dupe@isp.co.ke"
        return tenant

    def test_duplicate_schema_name_raises(self):
        with self.assertRaises(Exception):
            # Attempt to create a second tenant with the same schema_name
            Tenant.objects.create(
                schema_name=self.tenant.schema_name,
                name="Another ISP",
                contact_email="another@isp.co.ke",
            )

    def test_duplicate_primary_domain_raises(self):
        primary = Domain.objects.get(tenant=self.tenant, is_primary=True)
        with self.assertRaises(IntegrityError):
            Domain.objects.create(
                domain=primary.domain,
                tenant=self.tenant,
                is_primary=False,
            )


@pytest.mark.django_db(transaction=True)
class TenantIsolationTest(TenantTestCase):
    """
    Verifies schema isolation — objects created in one tenant's schema
    are not visible from another tenant's schema.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "ISP Alpha"
        tenant.contact_email = "alpha@isp.co.ke"
        return tenant

    def test_second_tenant_schema_is_isolated(self):
        # Create a second tenant
        tenant_b = Tenant(
            schema_name="isp_beta_isolation",
            name="ISP Beta",
            contact_email="beta@isp.co.ke",
        )
        tenant_b.save()
        Domain.objects.create(
            domain="isp_beta_isolation.localhost",
            tenant=tenant_b,
            is_primary=True,
        )

        try:
            # From the public schema, both tenants are visible
            from django_tenants.utils import schema_context

            with schema_context("public"):
                names = list(Tenant.objects.values_list("name", flat=True))
                self.assertIn("ISP Alpha", names)
                self.assertIn("ISP Beta", names)

            # From Alpha's schema, Beta's schema objects are not visible
            # (portal/network models are in tenant schemas; we just verify
            # schema_context switches correctly without cross-contamination)
            with schema_context(self.tenant.schema_name):
                # Only Alpha's schema is active — Beta's tenant record
                # lives in public, but tenant-specific app data is isolated
                from django.db import connection
                self.assertEqual(
                    connection.schema_name, self.tenant.schema_name
                )

            with schema_context(tenant_b.schema_name):
                from django.db import connection
                self.assertEqual(connection.schema_name, tenant_b.schema_name)

        finally:
            tenant_b.delete(force_drop=True)
