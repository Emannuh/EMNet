"""
View-level tests for tenant onboarding.
Tests access control, form submission, and redirect behaviour.
These run against the public schema only (no schema creation needed).
"""
import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.tenants.models import Tenant, Domain

User = get_user_model()


def make_super_admin(email="super@netsuite.io", password="TestPass123!"):
    return User.objects.create_user(
        email=email,
        password=password,
        role=User.Role.SUPER_ADMIN,
        is_staff=True,
    )


def make_isp_admin(email="ispadmin@isp.co.ke", password="TestPass123!"):
    return User.objects.create_user(
        email=email,
        password=password,
        role=User.Role.ISP_ADMIN,
    )


VALID_PAYLOAD = {
    "name": "View Test ISP",
    "schema_name": "view_test_isp",
    "contact_email": "contact@viewtest.co.ke",
    "contact_phone": "",
    "admin_full_name": "View Admin",
    "admin_email": "viewadmin@viewtest.co.ke",
    "admin_password": "Str0ngPass!",
    "admin_password_confirm": "Str0ngPass!",
}


@pytest.mark.django_db
class TenantListViewAccessTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("tenants:list")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"/accounts/login/?next={self.url}")

    def test_isp_admin_forbidden(self):
        user = make_isp_admin()
        self.client.force_login(user)
        response = self.client.get(self.url)
        # UserPassesTestMixin returns 403
        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_access(self):
        user = make_super_admin()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ISP Tenants")


@pytest.mark.django_db
class TenantCreateViewAccessTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("tenants:create")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"/accounts/login/?next={self.url}")

    def test_isp_admin_forbidden(self):
        user = make_isp_admin()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_super_admin_sees_form(self):
        user = make_super_admin()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schema / Subdomain")


@pytest.mark.django_db(transaction=True)
class TenantCreateSubmitTest(TestCase):
    """
    Tests actual tenant creation via POST.
    Uses transaction=True because django-tenants creates a Postgres schema
    which cannot run inside a transaction.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("tenants:create")
        self.super_admin = make_super_admin()
        self.client.force_login(self.super_admin)

    def test_valid_post_creates_tenant(self):
        response = self.client.post(self.url, VALID_PAYLOAD)
        self.assertRedirects(response, reverse("tenants:list"))
        self.assertTrue(Tenant.objects.filter(schema_name="view_test_isp").exists())

    def test_valid_post_creates_domain(self):
        self.client.post(self.url, VALID_PAYLOAD)
        self.assertTrue(
            Domain.objects.filter(domain="view_test_isp.localhost", is_primary=True).exists()
        )

    def test_valid_post_creates_isp_admin_user(self):
        self.client.post(self.url, VALID_PAYLOAD)
        user = User.objects.filter(email="viewadmin@viewtest.co.ke").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, User.Role.ISP_ADMIN)

    def test_duplicate_schema_shows_form_error(self):
        # First submission — succeeds
        self.client.post(self.url, VALID_PAYLOAD)
        # Second submission — same schema_name
        response = self.client.post(self.url, VALID_PAYLOAD)
        self.assertEqual(response.status_code, 200)  # form re-rendered
        self.assertContains(response, "already exists")

    def test_duplicate_admin_email_shows_form_error(self):
        self.client.post(self.url, VALID_PAYLOAD)
        # Try a new schema but same admin email
        payload2 = {**VALID_PAYLOAD, "schema_name": "another_isp", "name": "Another ISP"}
        response = self.client.post(self.url, payload2)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_password_mismatch_shows_form_error(self):
        payload = {**VALID_PAYLOAD, "admin_password_confirm": "WrongPass!"}
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match")
        self.assertFalse(Tenant.objects.filter(schema_name="view_test_isp").exists())
