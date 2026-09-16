from django.urls import path
from django.views.generic import TemplateView

app_name = "portal"

urlpatterns = [
    path("", TemplateView.as_view(template_name="portal/index.html"), name="index"),
]
