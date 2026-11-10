from django.urls import path
from .views import (
    DashboardView, RevenueView, DisputeQueueView, SettingsListView,
)

urlpatterns = [
    path("admin/dashboard/", DashboardView.as_view()),
    path("admin/revenue/", RevenueView.as_view()),
    path("admin/queue/disputes/", DisputeQueueView.as_view()),
    path("admin/settings/", SettingsListView.as_view()),
]