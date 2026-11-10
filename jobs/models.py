import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone

from accounts.models import Skill


class Job(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open for bids"
        BID_ACCEPTED = "bid_accepted", "Bid accepted"
        IN_PROGRESS = "in_progress", "In progress"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        DISPUTED = "disputed", "Disputed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="jobs_posted",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    deadline = models.DateTimeField()
    budget_min = models.DecimalField(max_digits=14, decimal_places=2)
    budget_max = models.DecimalField(max_digits=14, decimal_places=2)

    # Decision #1: client sets minimum level + required skills
    min_level = models.PositiveSmallIntegerField(default=1)
    required_skills = models.ManyToManyField(Skill, blank=True, related_name="jobs")

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT,
    )

    # Bidding window
    bid_window_ends_at = models.DateTimeField()
    max_bids = models.PositiveIntegerField(default=50)
    bid_count = models.PositiveIntegerField(default=0)

    # Decision #3: pass cost frozen at post time (budget-derived)
    pass_cost = models.PositiveIntegerField(default=1)

    # Accepted-bid linkage
    accepted_bid = models.OneToOneField(
        "Bid", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="accepted_for_job",
    )
    agreed_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )

    # Delivery + review
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_text = models.TextField(blank=True)
    delivery_file_url = models.URLField(blank=True)

    # Decision #4: hard cap 2 revisions
    revisions_used = models.SmallIntegerField(default=0)

    # Decision #5: auto-approve 5 days after delivery
    auto_approve_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "bid_window_ends_at"]),
            models.Index(fields=["client", "status"]),
        ]

    def __str__(self):
        return f"{self.title} [{self.status}]"

    def is_biddable(self):
        return (
            self.status == self.Status.OPEN
            and self.bid_window_ends_at > timezone.now()
            and self.bid_count < self.max_bids
        )

    def can_revise(self):
        from config.settings_helpers import get_max_revisions
        return self.revisions_used < get_max_revisions()


class Bid(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="bids")
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="bids",
    )
    price = models.DecimalField(max_digits=14, decimal_places=2)
    delivery_days = models.PositiveSmallIntegerField()
    message = models.TextField(blank=True)

    # Decision #2: score breakdown is stored per bid for audit
    score_total = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
    )
    score_breakdown = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SUBMITTED,
    )
    pass_reference = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("job", "worker")]
        ordering = ["-score_total", "created_at"]
        indexes = [models.Index(fields=["job", "-score_total"])]

    def __str__(self):
        return f"Bid {self.price} by {self.worker_id} on {self.job_id}"