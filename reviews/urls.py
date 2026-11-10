from django.urls import path
from .views import RateJobView, WorkerReviewsView

urlpatterns = [
    path("jobs/<uuid:pk>/rate/", RateJobView.as_view(), name="job-rate"),
    path("workers/<uuid:worker_id>/reviews/", WorkerReviewsView.as_view(), name="worker-reviews"),
]