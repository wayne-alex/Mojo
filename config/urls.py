from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/jobs/", include("jobs.urls")),
    path("api/payouts/", include("payouts.urls")),
    path("api/", include("reviews.urls")),
    path("api/", include("disputes.urls")),
    path("api/", include("fraud.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("adminpanel.urls")),
]