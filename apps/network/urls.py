from django.urls import path
from django.views.generic import TemplateView

app_name = "network"

urlpatterns = [
    path("", TemplateView.as_view(template_name="network/index.html"), name="index"),
]
