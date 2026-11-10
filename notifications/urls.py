from django.urls import path
from .cron_views import CronAutoApproveView, CronReleaseHoldsView, CronPurgeOTPsView
from .views import NotificationListView, MarkReadView, MarkAllReadView

urlpatterns = [
    path("internal/cron/auto-approve/", CronAutoApproveView.as_view()),
    path("internal/cron/release-holds/", CronReleaseHoldsView.as_view()),
path("internal/cron/purge-otps/", CronPurgeOTPsView.as_view()),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/<uuid:pk>/read/", MarkReadView.as_view()),
    path("notifications/mark-all-read/", MarkAllReadView.as_view()),
]