"""
Network dashboard views — device management, alert rules, and bandwidth charts.
All views require login; ISP-scoped (run inside tenant schema).
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.http import HttpResponseRedirect, JsonResponse
from django.views import View
from django.utils import timezone
from datetime import timedelta

from .models import Device, UptimeEvent, AlertRule, BandwidthSnapshot


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


# ── Alert Rules ───────────────────────────────────────────────────────────────

class AlertRuleListView(LoginRequiredMixin, ListView):
    model = AlertRule
    template_name = "network/alert_rules.html"
    context_object_name = "rules"
    paginate_by = 25

    def get_queryset(self):
        qs = AlertRule.objects.select_related("device").all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(notify_email__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["total"] = AlertRule.objects.count()
        ctx["active_count"] = AlertRule.objects.filter(is_active=True).count()
        return ctx


class AlertRuleCreateView(LoginRequiredMixin, CreateView):
    model = AlertRule
    template_name = "network/alert_rule_form.html"
    fields = ["name", "condition", "device", "threshold_mbps",
              "notify_email", "cooldown_minutes", "is_active"]
    success_url = reverse_lazy("network:alert_rules")

    def form_valid(self, form):
        messages.success(self.request, f'Alert rule "{form.instance.name}" created.')
        return super().form_valid(form)


class AlertRuleUpdateView(LoginRequiredMixin, UpdateView):
    model = AlertRule
    template_name = "network/alert_rule_form.html"
    fields = ["name", "condition", "device", "threshold_mbps",
              "notify_email", "cooldown_minutes", "is_active"]
    success_url = reverse_lazy("network:alert_rules")

    def form_valid(self, form):
        messages.success(self.request, f'Alert rule "{form.instance.name}" updated.')
        return super().form_valid(form)


class AlertRuleDeleteView(LoginRequiredMixin, DeleteView):
    model = AlertRule
    template_name = "network/alert_rule_confirm_delete.html"
    success_url = reverse_lazy("network:alert_rules")

    def form_valid(self, form):
        messages.success(self.request, f'Alert rule "{self.object.name}" deleted.')
        return super().form_valid(form)


# ── Bandwidth chart ───────────────────────────────────────────────────────────

class DeviceBandwidthView(LoginRequiredMixin, DetailView):
    """
    HTML page showing bandwidth chart for a single device.
    The chart is rendered client-side from /bandwidth/data/ JSON endpoint.
    """
    model = Device
    template_name = "network/device_bandwidth.html"
    context_object_name = "device"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Available time-range options
        ctx["ranges"] = [
            ("1h",  "Last 1 hour"),
            ("6h",  "Last 6 hours"),
            ("24h", "Last 24 hours"),
            ("7d",  "Last 7 days"),
        ]
        ctx["selected_range"] = self.request.GET.get("range", "1h")
        return ctx


class BandwidthChartDataView(LoginRequiredMixin, View):
    """
    JSON endpoint consumed by the bandwidth chart.
    Returns arrays of timestamps + Mbps values for the requested time range.

    Query params:
      range  — 1h | 6h | 24h | 7d  (default: 1h)

    Response:
      {
        "labels":    ["14:00", "14:05", ...],
        "bytes_in":  [1234567, ...],   # raw bytes
        "bytes_out": [...]
        "mbps_in":   [1.23, ...],      # Mbps (delta/interval)
        "mbps_out":  [...]
      }
    """

    RANGE_MAP = {
        "1h":  timedelta(hours=1),
        "6h":  timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d":  timedelta(days=7),
    }

    def get(self, request, pk):
        from django.shortcuts import get_object_or_404
        device = get_object_or_404(Device, pk=pk)

        range_key = request.GET.get("range", "1h")
        delta = self.RANGE_MAP.get(range_key, timedelta(hours=1))
        since = timezone.now() - delta

        snapshots = list(
            BandwidthSnapshot.objects.filter(
                device=device,
                timestamp__gte=since,
            ).order_by("timestamp").values("timestamp", "bytes_in", "bytes_out")
        )

        labels    = []
        mbps_in   = []
        mbps_out  = []

        for i, snap in enumerate(snapshots):
            ts = snap["timestamp"]
            if range_key in ("1h", "6h"):
                label = ts.strftime("%H:%M")
            elif range_key == "24h":
                label = ts.strftime("%H:%M")
            else:
                label = ts.strftime("%d %b %H:%M")
            labels.append(label)

            # Calculate Mbps delta between consecutive snapshots
            if i == 0:
                mbps_in.append(0)
                mbps_out.append(0)
            else:
                prev = snapshots[i - 1]
                seconds = max(
                    (ts - prev["timestamp"]).total_seconds(), 1
                )
                in_bytes  = max(snap["bytes_in"]  - prev["bytes_in"],  0)
                out_bytes = max(snap["bytes_out"] - prev["bytes_out"], 0)
                mbps_in.append(round((in_bytes  * 8) / seconds / 1_000_000, 3))
                mbps_out.append(round((out_bytes * 8) / seconds / 1_000_000, 3))

        return JsonResponse({
            "device_name": device.name,
            "labels":   labels,
            "mbps_in":  mbps_in,
            "mbps_out": mbps_out,
            "snapshot_count": len(snapshots),
        })
