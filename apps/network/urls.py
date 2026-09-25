from django.urls import path
from . import views

app_name = "network"

urlpatterns = [
    path("", views.DeviceListView.as_view(), name="index"),
    path("devices/add/", views.DeviceCreateView.as_view(), name="device_add"),
    path("devices/<int:pk>/edit/", views.DeviceUpdateView.as_view(), name="device_edit"),
    path("devices/<int:pk>/delete/", views.DeviceDeleteView.as_view(), name="device_delete"),
    # Alert Rules
    path("alerts/", views.AlertRuleListView.as_view(), name="alert_rules"),
    path("alerts/add/", views.AlertRuleCreateView.as_view(), name="alert_rule_add"),
    path("alerts/<int:pk>/edit/", views.AlertRuleUpdateView.as_view(), name="alert_rule_edit"),
    path("alerts/<int:pk>/delete/", views.AlertRuleDeleteView.as_view(), name="alert_rule_delete"),
    # Bandwidth chart
    path("devices/<int:pk>/bandwidth/", views.DeviceBandwidthView.as_view(), name="device_bandwidth"),
    path("devices/<int:pk>/bandwidth/data/", views.BandwidthChartDataView.as_view(), name="bandwidth_data"),
]
