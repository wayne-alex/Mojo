from django.urls import path
from .views import (
    JobCreateView, JobFeedView, MyJobsView, JobDetailView,
    BidCreateView, TopBidsView, AcceptBidView,
    DeliverView, ApproveView, ReviseView, CancelView,
)

urlpatterns = [
    path("", JobCreateView.as_view(), name="job-create"),
    path("feed/", JobFeedView.as_view(), name="job-feed"),
    path("my/", MyJobsView.as_view(), name="job-my"),
    path("<uuid:pk>/", JobDetailView.as_view(), name="job-detail"),
    path("<uuid:pk>/bids/", BidCreateView.as_view(), name="job-bid-create"),
    path("<uuid:pk>/top-bids/", TopBidsView.as_view(), name="job-top-bids"),
    path("<uuid:pk>/accept/<uuid:bid_id>/", AcceptBidView.as_view(), name="job-accept"),
    path("<uuid:pk>/deliver/", DeliverView.as_view(), name="job-deliver"),
    path("<uuid:pk>/approve/", ApproveView.as_view(), name="job-approve"),
    path("<uuid:pk>/revise/", ReviseView.as_view(), name="job-revise"),
    path("<uuid:pk>/cancel/", CancelView.as_view(), name="job-cancel"),
]