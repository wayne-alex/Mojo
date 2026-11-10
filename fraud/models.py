import uuid
from django.db import models
from django.conf import settings


class RateLimitHit(models.Model):
    """
    Rolling counter. One row per (endpoint, identity, window_start).
    Incremented with select_for_update to be safe under concurrency.
    """
    endpoint = models.CharField(max_length=64)          # "register" | "bid" | "withdraw"
    identity = models.CharField(max_length=128, db_index=True)  # user_id or ip
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("endpoint", "identity", "window_start")]
        indexes = [models.Index(fields=["endpoint", "identity"])]


class DeviceFingerprint(models.Model):
    """Recorded at signup. Admin view shows accounts sharing IP / device hash."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="device_fingerprints",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["ip"])]


class FraudFlag(models.Model):
    """Audit log of automatic or manual flags."""
    class Reason(models.TextChoices):
        MULTI_ACCOUNT = "multi_account", "Multiple accounts"
        RATE_LIMIT = "rate_limit", "Rate limit abused"
        CHARGEBACK = "chargeback", "Chargeback"
        SPAM = "spam", "Spam content"
        MANUAL = "manual", "Manual admin flag"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="fraud_flags",
    )
    reason = models.CharField(max_length=32, choices=Reason.choices)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="fraud_flags_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]