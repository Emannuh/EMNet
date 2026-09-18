from django.contrib import admin
from .models import (
    ServicePlan, IpPool, IpAddress,
    Subscriber, Subscription, Invoice, InvoicePayment,
)


@admin.register(ServicePlan)
class ServicePlanAdmin(admin.ModelAdmin):
    list_display = ["name", "connection_type", "download_mbps", "upload_mbps",
                    "price_kes", "billing_cycle", "is_active"]
    list_filter = ["connection_type", "billing_cycle", "is_active"]
    search_fields = ["name"]


class IpAddressInline(admin.TabularInline):
    model = IpAddress
    extra = 0
    fields = ["address", "status"]


@admin.register(IpPool)
class IpPoolAdmin(admin.ModelAdmin):
    list_display = ["name", "network", "gateway", "is_active"]
    inlines = [IpAddressInline]


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    fields = ["plan", "status", "start_date", "next_due_date"]
    readonly_fields = ["start_date", "next_due_date"]


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ["full_name", "pppoe_username", "phone", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["full_name", "phone", "pppoe_username", "cpe_serial"]
    inlines = [SubscriptionInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["subscriber", "plan", "status", "start_date", "next_due_date"]
    list_filter = ["status", "plan"]
    search_fields = ["subscriber__full_name", "subscriber__pppoe_username"]


class InvoicePaymentInline(admin.TabularInline):
    model = InvoicePayment
    extra = 0
    fields = ["phone_number", "amount_kes", "mpesa_receipt_number", "status"]
    readonly_fields = ["created_at"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["reference", "subscriber_name", "amount_kes",
                    "due_date", "status"]
    list_filter = ["status"]
    search_fields = ["subscription__subscriber__full_name",
                     "mpesa_checkout_request_id"]
    readonly_fields = ["reference", "created_at", "updated_at"]
    inlines = [InvoicePaymentInline]

    @admin.display(description="Subscriber")
    def subscriber_name(self, obj):
        return obj.subscription.subscriber.full_name


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ["invoice", "phone_number", "amount_kes",
                    "mpesa_receipt_number", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["phone_number", "mpesa_receipt_number"]
    readonly_fields = ["created_at", "updated_at"]
