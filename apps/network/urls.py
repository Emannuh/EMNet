from django.urls import path
from . import views

app_name = "network"

urlpatterns = [
    path("", views.DeviceListView.as_view(), name="index"),
    path("devices/add/", views.DeviceCreateView.as_view(), name="device_add"),
    path("devices/<int:pk>/edit/", views.DeviceUpdateView.as_view(), name="device_edit"),
    path("devices/<int:pk>/delete/", views.DeviceDeleteView.as_view(), name="device_delete"),
]
