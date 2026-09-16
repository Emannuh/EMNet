"""
Root URL configuration for NetSuite-ISP.
Public (shared) schema routes live here.
Tenant-specific routes are included via each app's urls.py.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.network.urls")),
    path("portal-admin/", include("apps.portal.urls")),
    path("billing/", include("apps.billing.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
