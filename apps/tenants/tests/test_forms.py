"""
Unit tests for TenantOnboardingForm validation.
These run without hitting the database for schema creation —
they test form-level validation only.
"""
import pytest
from django.test import TestCase
from apps.tenants.forms import TenantOnboardingForm

VALID_DATA = {
    "name": "Acme Internet",
    "schema_name": "acme_internet",
    "contact_email": "contact@acme.co.ke",
    "contact_phone": "+254700000000",
    "admin_full_name": "Alice Admin",
    "admin_email": "alice@acme.co.ke",
    "admin_password": "Str0ngPass!",
    "admin_password_confirm": "Str0ngPass!",
}


class TenantOnboardingFormValidationTest(TestCase):

    def _form(self, overrides=None):
        data = {**VALID_DATA, **(overrides or {})}
        return TenantOnboardingForm(data=data)

    # ── Happy path ────────────────────────────────────────────────────────────
    def test_valid_data_passes(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)

    # ── Schema name rules ─────────────────────────────────────────────────────
    def test_schema_must_start_with_letter(self):
        form = self._form({"schema_name": "1acme"})
        self.assertFalse(form.is_valid())
        self.assertIn("schema_name", form.errors)

    def test_schema_uppercase_rejected(self):
        form = self._form({"schema_name": "AcmeInternet"})
        # SlugField lowercases, but our regex rejects uppercase — check normalised
        self.assertFalse(form.is_valid())
        self.assertIn("schema_name", form.errors)

    def test_schema_too_short(self):
        form = self._form({"schema_name": "ab"})
        self.assertFalse(form.is_valid())
        self.assertIn("schema_name", form.errors)

    def test_schema_reserved_word_rejected(self):
        for reserved in ("public", "admin", "www"):
            with self.subTest(schema=reserved):
                form = self._form({"schema_name": reserved})
                self.assertFalse(form.is_valid())
                self.assertIn("schema_name", form.errors)

    def test_schema_hyphens_rejected(self):
        form = self._form({"schema_name": "acme-internet"})
        self.assertFalse(form.is_valid())
        self.assertIn("schema_name", form.errors)

    def test_schema_valid_with_underscores(self):
        form = self._form({"schema_name": "acme_internet_ke"})
        self.assertTrue(form.is_valid(), form.errors)

    # ── Password rules ────────────────────────────────────────────────────────
    def test_password_mismatch_rejected(self):
        form = self._form({"admin_password_confirm": "WrongPass!"})
        self.assertFalse(form.is_valid())
        self.assertIn("admin_password_confirm", form.errors)

    def test_password_too_short_rejected(self):
        form = self._form({"admin_password": "short", "admin_password_confirm": "short"})
        self.assertFalse(form.is_valid())

    # ── Email rules ───────────────────────────────────────────────────────────
    def test_invalid_contact_email_rejected(self):
        form = self._form({"contact_email": "not-an-email"})
        self.assertFalse(form.is_valid())
        self.assertIn("contact_email", form.errors)

    def test_invalid_admin_email_rejected(self):
        form = self._form({"admin_email": "not-an-email"})
        self.assertFalse(form.is_valid())
        self.assertIn("admin_email", form.errors)
