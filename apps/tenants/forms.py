"""
Tenant onboarding forms.
TenantOnboardingForm collects everything needed to provision a new ISP
in a single transaction: Tenant record, Postgres schema, Domain, and
the first ISP admin user.
"""
import re
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import Tenant, Domain

User = get_user_model()

SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


class TenantOnboardingForm(forms.Form):
    # ── ISP details ──────────────────────────────────────────────────────────
    name = forms.CharField(
        max_length=200,
        label="ISP Name",
        widget=forms.TextInput(attrs={"placeholder": "Acme Internet Ltd"}),
    )
    schema_name = forms.SlugField(
        max_length=63,
        label="Schema / subdomain",
        help_text="Lowercase letters, digits and underscores only. "
                  "This becomes the Postgres schema and the default subdomain. "
                  "Cannot be changed later.",
        widget=forms.TextInput(attrs={"placeholder": "acme_internet"}),
    )
    contact_email = forms.EmailField(label="ISP Contact Email")
    contact_phone = forms.CharField(max_length=30, required=False, label="Contact Phone")

    # ── First ISP admin user ─────────────────────────────────────────────────
    admin_full_name = forms.CharField(max_length=200, label="Admin Full Name")
    admin_email = forms.EmailField(label="Admin Email")
    admin_password = forms.CharField(
        label="Admin Password",
        widget=forms.PasswordInput,
        min_length=8,
    )
    admin_password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput,
    )

    def clean_schema_name(self):
        value = self.cleaned_data["schema_name"].lower()
        if not SCHEMA_RE.match(value):
            raise ValidationError(
                "Schema name must start with a letter and contain only "
                "lowercase letters, digits, and underscores (3–63 chars)."
            )
        reserved = {"public", "information_schema", "pg_catalog", "admin", "www"}
        if value in reserved:
            raise ValidationError(f'"{value}" is a reserved name.')
        if Tenant.objects.filter(schema_name=value).exists():
            raise ValidationError("A tenant with this schema name already exists.")
        return value

    def clean_admin_email(self):
        email = self.cleaned_data["admin_email"]
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("admin_password")
        pw2 = cleaned.get("admin_password_confirm")
        if pw and pw2 and pw != pw2:
            self.add_error("admin_password_confirm", "Passwords do not match.")
        return cleaned


class TenantEditForm(forms.ModelForm):
    """Allow super-admin to update ISP name, contact info and active status."""

    class Meta:
        model = Tenant
        fields = ["name", "contact_email", "contact_phone", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-control"}),
            "contact_phone": forms.TextInput(attrs={"class": "form-control"}),
        }
