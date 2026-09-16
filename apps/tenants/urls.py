from django.urls import path
from . import views

app_name = "tenants"

urlpatterns = [
    path("", views.TenantListView.as_view(), name="list"),
    path("create/", views.TenantCreateView.as_view(), name="create"),
    path("<slug:schema_name>/", views.TenantDetailView.as_view(), name="detail"),
    path("<slug:schema_name>/edit/", views.TenantUpdateView.as_view(), name="edit"),
    path("<slug:schema_name>/toggle/", views.TenantToggleActiveView.as_view(), name="toggle"),
]
