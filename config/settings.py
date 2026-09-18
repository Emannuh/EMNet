"""
NetSuite-ISP  —  Django settings
Uses django-tenants (schema-per-tenant on Postgres).
All secrets are read from environment / .env via django-environ.
"""
import environ
from pathlib import Path

# ── Base paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

# ── Core ──────────────────────────────────────────────────────────────────────
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "deenet.localhost"])

# CSRF trusted origins — must include every scheme+host the browser posts from
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8000",
        "http://localhost:8090",
        "http://127.0.0.1:8090",
        "http://deenet.localhost:8090",
        "http://deenet.localhost:8080",
    ],
)

# ── django-tenants ────────────────────────────────────────────────────────────
# Must be first in INSTALLED_APPS
SHARED_APPS = [
    "django_tenants",           # tenant machinery
    "apps.tenants",             # our Tenant + Domain models

    # Standard Django shared apps
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",

    # Third-party shared
    "django_celery_beat",
    "django_celery_results",
    "django_htmx",
    "crispy_forms",
    "crispy_bootstrap5",

    # Our shared apps (super-admin lives in public schema)
    "apps.accounts",
]

TENANT_APPS = [
    # Apps that are replicated per tenant schema
    "django.contrib.contenttypes",
    "django.contrib.auth",

    "apps.portal",
    "apps.network",
    "apps.billing",
    "apps.radius",
    "apps.subscribers",
]

INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # must be first
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

# ── Templates ─────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": env("POSTGRES_DB", default="netsuite_isp"),
        "USER": env("POSTGRES_USER", default="netsuite"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    },
    # Separate RADIUS database used by FreeRADIUS (not tenant-switched)
    "radius": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("RADIUS_DB_NAME", default="radius"),
        "USER": env("RADIUS_DB_USER", default="radius"),
        "PASSWORD": env("RADIUS_DB_PASSWORD"),
        "HOST": env("RADIUS_DB_HOST", default="db"),
        "PORT": env("RADIUS_DB_PORT", default="5432"),
    },
}

DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]

# ── Cache / Redis ─────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/2")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Nairobi"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ── Celery Beat schedule ──────────────────────────────────────────────────────
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # ── Network: SNMP device polling every 5 minutes ──────────────────────
    "snmp-poll-all-tenants": {
        "task": "network.poll_all_tenants",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "default"},
    },

    # ── Subscribers: generate invoices daily at 06:00 EAT ─────────────────
    "subscriber-generate-invoices": {
        "task": "subscribers.generate_invoices_for_all_tenants",
        "schedule": crontab(hour=6, minute=0),
        "options": {"queue": "default"},
    },

    # ── Subscribers: payment reminders daily at 08:00 EAT ─────────────────
    "subscriber-payment-reminders": {
        "task": "subscribers.send_payment_reminders_for_all_tenants",
        "schedule": crontab(hour=8, minute=0),
        "options": {"queue": "default"},
    },

    # ── Subscribers: overdue check + auto-suspend daily at 09:00 EAT ──────
    "subscriber-overdue-check": {
        "task": "subscribers.check_overdue_for_all_tenants",
        "schedule": crontab(hour=9, minute=0),
        "options": {"queue": "default"},
    },
}

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/accounts/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ── Static & media ────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# ── Crispy Forms ──────────────────────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# ── M-Pesa ────────────────────────────────────────────────────────────────────
MPESA_ENVIRONMENT = env("MPESA_ENVIRONMENT", default="sandbox")
MPESA_CONSUMER_KEY = env("MPESA_CONSUMER_KEY", default="")
MPESA_CONSUMER_SECRET = env("MPESA_CONSUMER_SECRET", default="")
MPESA_SHORTCODE = env("MPESA_SHORTCODE", default="174379")
MPESA_PASSKEY = env("MPESA_PASSKEY", default="")
MPESA_CALLBACK_BASE_URL = env("MPESA_CALLBACK_BASE_URL", default="https://localhost")

# ── Internal service URLs ─────────────────────────────────────────────────────
PORTAL_INTERNAL_URL = env("PORTAL_INTERNAL_URL", default="http://portal:8001")

# ── Sentry (optional) ─────────────────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.2)

# ── Default primary key ───────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
