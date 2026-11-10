import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator


class Wallet(models.Model):
    """A balance holder. Four types per spec section 8."""
    class Type(models.TextChoices):
        CLIENT = "client", "Client wallet"
        WORKER_EARNINGS = "worker_earnings", "Worker earnings"
        WORKER_PASS = "worker_pass", "Worker pass balance"
        PLATFORM = "platform", "Platform wallet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="wallets",
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    pending_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    available_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("owner", "type")]
        indexes = [models.Index(fields=["owner", "type"])]

    def __str__(self):
        return f"{self.type} wallet of {self.owner_id}"


class Transaction(models.Model):
    """Immutable ledger row. Never UPDATE this table — only INSERT."""
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit (M-Pesa/card in)"
        ESCROW_HOLD = "escrow_hold", "Client → escrow"
        ESCROW_RELEASE = "escrow_release", "Escrow → worker pending"
        ESCROW_REFUND = "escrow_refund", "Escrow → client (refund)"
        PENDING_TO_AVAILABLE = "pending_to_available", "Hold cleared"
        WITHDRAWAL = "withdrawal", "Available → M-Pesa out"
        WITHDRAWAL_REFUND = "withdrawal_refund", "Failed payout back to available"
        PLATFORM_FEE = "platform_fee", "Fee to platform"
        PASS_PURCHASE = "pass_purchase", "Buy passes / daily grant"
        PASS_DEDUCT = "pass_deduct", "Spend passes"
        PASS_REFUND = "pass_refund", "Refund passes"
        ADJUSTMENT = "adjustment", "Admin adjustment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REVERSED = "reversed", "Reversed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    amount = models.DecimalField(max_digits=14, decimal_places=2)   # signed: +credit, -debit
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=128, db_index=True)     # "job:{uuid}", "payout:{uuid}"
    meta = models.JSONField(default=dict, blank=True)
    cleared = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["reference"]),
        ]


class EscrowHold(models.Model):
    """One row per held job budget. Released or refunded exactly once."""
    class Status(models.TextChoices):
        HELD = "held", "Held"
        RELEASED = "released", "Released to worker"
        REFUNDED = "refunded", "Refunded to client"
        SPLIT = "split", "Split (dispute)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="escrow_holds")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.HELD)
    reference = models.CharField(max_length=128, unique=True)   # "job:{uuid}"
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)