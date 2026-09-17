"""
Network dashboard views — device management for ISP staff.
All views require login; ISP-scoped (run inside tenant schema).
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.http import HttpResponseRedirect

from .models import Device, UptimeEvent


class DeviceListView(LoginRequiredMixin, ListView):
    model = Device
    template_name = "network/index.html"
    context_object_name = "devices"
    paginate_by = 25

    def get_queryset(self):
        qs = Device.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(ip_address__icontains=q)
        status = self.request.GET.get("status", "")
        if status in Device.Status.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = Device.Status.choices
        ctx["device_type_choices"] = Device.DeviceType.choices
        ctx["total"] = Device.objects.count()
        ctx["up"] = Device.objects.filter(status=Device.Status.UP).count()
        ctx["down"] = Device.objects.filter(status=Device.Status.DOWN).count()
        ctx["unknown"] = Device.objects.filter(status=Device.Status.UNKNOWN).count()
        return ctx


class DeviceCreateView(LoginRequiredMixin, CreateView):
    model = Device
    template_name = "network/device_form.html"
    fields = ["name", "ip_address", "device_type", "location",
              "snmp_community", "snmp_version", "is_active"]
    success_url = reverse_lazy("network:index")

    def form_valid(self, form):
        messages.success(self.request, f'Device "{form.instance.name}" added.')
        return super().form_valid(form)


class DeviceUpdateView(LoginRequiredMixin, UpdateView):
    model = Device
    template_name = "network/device_form.html"
    fields = ["name", "ip_address", "device_type", "location",
              "snmp_community", "snmp_version", "is_active"]
    success_url = reverse_lazy("network:index")

    def form_valid(self, form):
        messages.success(self.request, f'Device "{form.instance.name}" updated.')
        return super().form_valid(form)


class DeviceDeleteView(LoginRequiredMixin, DeleteView):
    model = Device
    template_name = "network/device_confirm_delete.html"
    success_url = reverse_lazy("network:index")

    def form_valid(self, form):
        messages.success(self.request, f'Device "{self.object.name}" deleted.')
        return super().form_valid(form)
