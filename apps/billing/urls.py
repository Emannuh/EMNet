from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    path("", views.PaymentListView.as_view(), name="index"),
    path("stk-push/", views.StkPushView.as_view(), name="stk_push"),
    path("mpesa/callback/", views.MpesaCallbackView.as_view(), name="mpesa_callback"),
]
