import uuid
from django.db import models
from django.conf import settings


class Dispute(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UNDER_REVIEW = "under_review", "Under review"
        RESOLVED_PAY_WORKER = "resolved_pay_worker", "Resolved: pay worker"
        RESOLVED_REFUND_CLIENT = "resolved_refund_client", "Resolved: refund client"
        RESOLVED_SPLIT = "resolved_split", "Resolved: split"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "jobs.Job", on_delete=models.PROTECT, related_name="dispute",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="disputes_opened",
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN,
    )

    # Resolution
    resolution_note = models.TextField(blank=True)
    client_refund = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    worker_payout = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="disputes_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dispute {self.id} on {self.job_id} [{self.status}]"


class Evidence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispute = models.ForeignKey(Dispute, on_delete=models.CASCADE, related_name="evidence")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="evidence_submitted",
    )
    text = models.TextField(blank=True)
    file_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]