from django.urls import path

from .views import WithdrawalCreateView, WithdrawalListView, MpesaCallbackView, PaystackInitiateView, \
    PaystackWebhookView

urlpatterns = [
    path("withdrawals/", WithdrawalCreateView.as_view(), name="withdrawal-create"),
    path("withdrawals/list/", WithdrawalListView.as_view(), name="withdrawal-list"),
    path("mpesa/callback/", MpesaCallbackView.as_view(), name="mpesa-callback"),
    path("paystack/initiate/", PaystackInitiateView.as_view()),
    path("paystack/webhook/", PaystackWebhookView.as_view()),
]
