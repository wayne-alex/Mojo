import uuid
from django.db import models
from django.conf import settings


class Notification(models.Model):
    class Kind(models.TextChoices):
        BID_ACCEPTED = "bid_accepted", "Bid accepted"
        BID_LOST = "bid_lost", "Bid lost"
        DELIVERED = "delivered", "Job delivered"
        APPROVED = "approved", "Payment released"
        REVISION_REQUESTED = "revision_requested", "Revision requested"
        DISPUTE_OPENED = "dispute_opened", "Dispute opened"
        DISPUTE_RESOLVED = "dispute_resolved", "Dispute resolved"
        WITHDRAWAL_PAID = "withdrawal_paid", "Withdrawal paid"
        WITHDRAWAL_FAILED = "withdrawal_failed", "Withdrawal failed"
        RATING_RECEIVED = "rating_received", "Rating received"
        GENERIC = "generic", "Notice"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=500, blank=True)   # deep-link ref, e.g. "/jobs/{id}"
    reference = models.CharField(max_length=128, blank=True, db_index=True)  # job_id etc.
    read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read"])]

    def __str__(self):
        return f"{self.kind} → {self.user_id}"