from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"


class LogoutView(auth_views.LogoutView):
    pass


class DashboardRedirectView(TemplateView):
    """Temporary landing page — will be replaced by network dashboard."""
    template_name = "accounts/dashboard.html"
