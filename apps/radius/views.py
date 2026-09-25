"""
RADIUS NAS management views.
ISP staff can register and manage NAS devices (routers/APs) that
authenticate against FreeRADIUS. All views require login.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import RadiusNas


class NasListView(LoginRequiredMixin, ListView):
    model = RadiusNas
    template_name = "radius/index.html"
    context_object_name = "nas_devices"
    paginate_by = 25

    def get_queryset(self):
        qs = RadiusNas.objects.using("radius").all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(nasname__icontains=q) | qs.filter(shortname__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["total"] = RadiusNas.objects.using("radius").count()
        return ctx


class NasCreateView(LoginRequiredMixin, CreateView):
    model = RadiusNas
    template_name = "radius/nas_form.html"
    fields = ["nasname", "shortname", "type", "ports", "secret",
              "community", "description"]
    success_url = reverse_lazy("radius:index")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance._state.db = "radius"
        return form

    def form_valid(self, form):
        form.instance._state.db = "radius"
        response = super().form_valid(form)
        messages.success(self.request, f'NAS "{form.instance.nasname}" added.')
        return response


class NasUpdateView(LoginRequiredMixin, UpdateView):
    model = RadiusNas
    template_name = "radius/nas_form.html"
    fields = ["nasname", "shortname", "type", "ports", "secret",
              "community", "description"]
    success_url = reverse_lazy("radius:index")

    def get_object(self, queryset=None):
        return RadiusNas.objects.using("radius").get(pk=self.kwargs["pk"])

    def form_valid(self, form):
        form.instance._state.db = "radius"
        response = super().form_valid(form)
        messages.success(self.request, f'NAS "{form.instance.nasname}" updated.')
        return response


class NasDeleteView(LoginRequiredMixin, DeleteView):
    model = RadiusNas
    template_name = "radius/nas_confirm_delete.html"
    success_url = reverse_lazy("radius:index")

    def get_object(self, queryset=None):
        return RadiusNas.objects.using("radius").get(pk=self.kwargs["pk"])

    def form_valid(self, form):
        messages.success(self.request, f'NAS "{self.object.nasname}" removed.')
        return super().form_valid(form)
