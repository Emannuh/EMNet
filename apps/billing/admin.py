from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["reference", "phone_number", "amount_kes", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["phone_number", "mpesa_receipt_number", "reference"]
    readonly_fields = ["reference", "created_at", "updated_at"]
