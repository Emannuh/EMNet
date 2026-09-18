from django.urls import path
from . import views

app_name = "subscribers"

urlpatterns = [
    # Dashboard
    path("", views.SubscriberDashboardView.as_view(), name="dashboard"),

    # Service plans
    path("plans/", views.ServicePlanListView.as_view(), name="plan_list"),
    path("plans/add/", views.ServicePlanCreateView.as_view(), name="plan_add"),
    path("plans/<int:pk>/edit/", views.ServicePlanUpdateView.as_view(), name="plan_edit"),
    path("plans/<int:pk>/delete/", views.ServicePlanDeleteView.as_view(), name="plan_delete"),

    # IP pools
    path("ippools/", views.IpPoolListView.as_view(), name="ippool_list"),
    path("ippools/add/", views.IpPoolCreateView.as_view(), name="ippool_add"),
    path("ippools/<int:pk>/edit/", views.IpPoolUpdateView.as_view(), name="ippool_edit"),
    path("ippools/<int:pool_pk>/ip/add/", views.IpAddressCreateView.as_view(), name="ip_add"),

    # Subscribers
    path("subscribers/", views.SubscriberListView.as_view(), name="subscriber_list"),
    path("subscribers/add/", views.SubscriberCreateView.as_view(), name="subscriber_add"),
    path("subscribers/<int:pk>/", views.SubscriberDetailView.as_view(), name="subscriber_detail"),
    path("subscribers/<int:pk>/edit/", views.SubscriberUpdateView.as_view(), name="subscriber_edit"),

    # Subscription actions
    path("subscribers/<int:subscriber_pk>/assign/", views.SubscriptionAssignView.as_view(), name="subscription_assign"),
    path("subscribers/<int:pk>/suspend/", views.SubscriberSuspendView.as_view(), name="subscriber_suspend"),
    path("subscribers/<int:pk>/reactivate/", views.SubscriberReactivateView.as_view(), name="subscriber_reactivate"),
    path("subscribers/<int:pk>/cancel/", views.SubscriberCancelView.as_view(), name="subscriber_cancel"),
    path("subscribers/<int:pk>/change-plan/", views.PlanChangeView.as_view(), name="plan_change"),

    # Invoices
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<int:pk>/send-payment/", views.InvoiceSendPaymentView.as_view(), name="invoice_send_payment"),
    path("invoices/<int:pk>/mark-paid/", views.InvoiceMarkPaidView.as_view(), name="invoice_mark_paid"),
]
