from django.urls import path
from .views import SharedIpView, SharedDeviceView, FraudFlagListView

urlpatterns = [
    path("fraud/shared-ip/", SharedIpView.as_view()),
    path("fraud/shared-device/", SharedDeviceView.as_view()),
    path("fraud/flags/", FraudFlagListView.as_view()),
]