from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    # Voucher plans
    path("", views.VoucherPlanListView.as_view(), name="index"),
    path("plans/add/", views.VoucherPlanCreateView.as_view(), name="plan_add"),
    path("plans/<int:pk>/edit/", views.VoucherPlanUpdateView.as_view(), name="plan_edit"),
    path("plans/<int:pk>/delete/", views.VoucherPlanDeleteView.as_view(), name="plan_delete"),
    # Vouchers
    path("vouchers/", views.VoucherListView.as_view(), name="voucher_list"),
    # Sessions
    path("sessions/", views.WifiSessionListView.as_view(), name="session_list"),
]
