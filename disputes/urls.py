from django.urls import path
from .views import (
    OpenDisputeView, SubmitEvidenceView, ResolveDisputeView, DisputeDetailView,
)

urlpatterns = [
    path("jobs/<uuid:pk>/dispute/", OpenDisputeView.as_view(), name="job-dispute"),
    path("disputes/<uuid:pk>/evidence/", SubmitEvidenceView.as_view(), name="dispute-evidence"),
    path("disputes/<uuid:pk>/resolve/", ResolveDisputeView.as_view(), name="dispute-resolve"),
    path("disputes/<uuid:pk>/", DisputeDetailView.as_view(), name="dispute-detail"),
]