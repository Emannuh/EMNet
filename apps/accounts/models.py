"""
Custom User model for NetSuite-ISP.
Replaces Django's default User so we can add roles cleanly.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.SUPER_ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Platform user.  Roles:
      SUPER_ADMIN  — NetSuite-ISP platform operator (public schema)
      ISP_ADMIN    — ISP owner / account manager (tenant schema)
      ISP_STAFF    — ISP technician / NOC operator (tenant schema)
    """

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        ISP_ADMIN = "isp_admin", "ISP Admin"
        ISP_STAFF = "isp_staff", "ISP Staff"

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ISP_STAFF)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)   # Django admin access

    date_joined = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    @property
    def is_super_admin(self) -> bool:
        return self.role == self.Role.SUPER_ADMIN

    @property
    def is_isp_admin(self) -> bool:
        return self.role == self.Role.ISP_ADMIN
