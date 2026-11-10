from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView, LoginView, MeView,
    IssueOTPView, VerifyOTPView, ResendOTPView, AdminLookupOTPView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("otp/issue/", IssueOTPView.as_view(), name="auth-otp-issue"),
    path("otp/verify/", VerifyOTPView.as_view(), name="auth-otp-verify"),
    path("otp/resend/", ResendOTPView.as_view(), name="auth-otp-resend"),
path("admin/otp/lookup/", AdminLookupOTPView.as_view(), name="auth-admin-otp-lookup"),
]