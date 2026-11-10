import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings


class Withdrawal(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="withdrawals",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    mpesa_number = models.CharField(max_length=20)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.REQUESTED,
    )
    reference = models.CharField(max_length=128, unique=True)   # "payout:{uuid}"

    # M-Pesa B2C tracking
    conversation_id = models.CharField(max_length=128, blank=True)   # from B2C request
    originator_conversation_id = models.CharField(max_length=128, blank=True)
    mpesa_receipt = models.CharField(max_length=64, blank=True)      # from callback
    failure_reason = models.TextField(blank=True)

    requested_at = models.DateTimeField(auto_now_add=True)
    processing_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "requested_at"]),
        ]

    def __str__(self):
        return f"{self.amount} → {self.mpesa_number} [{self.status}]"

class PendingPayment(models.Model):
    class Purpose(models.TextChoices):
        CLIENT_DEPOSIT = "client_deposit", "Client wallet deposit"
        PASS_PURCHASE = "pass_purchase", "Pass purchase"

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name="pending_payments")
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    # For pass purchases, how many passes they're buying
    pass_count = models.PositiveIntegerField(default=0)

    reference = models.CharField(max_length=128, unique=True)   # sent to Paystack
    status = models.CharField(max_length=16, choices=Status.choices,
                              default=Status.INITIATED)
    paystack_ref = models.CharField(max_length=128, blank=True)  # Paystack's own ref
    provider_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reference"]),
            models.Index(fields=["user", "status"]),
        ]

    @property
    def authorization_url(self):
        return self.provider_response.get("authorization_url", "")