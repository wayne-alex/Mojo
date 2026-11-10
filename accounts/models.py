import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class Skill(models.Model):
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        WORKER = "worker", "Worker"
        CLIENT = "client", "Client"
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=16, choices=Role.choices)
    phone = models.CharField(max_length=20, unique=True, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username or self.phone} ({self.role})"


class WorkerProfile(models.Model):
    """Everything the bid scoring engine reads for a worker."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="worker_profile",
    )

    # Level (earned, per spec section 3)
    level = models.PositiveSmallIntegerField(default=1)

    # Quality signals used in bid scoring
    accuracy_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    avg_rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    completion_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    # Counters
    completed_jobs = models.PositiveIntegerField(default=0)
    total_jobs_started = models.PositiveIntegerField(default=0)
    total_tasks_approved = models.PositiveIntegerField(default=0)
    total_tasks_rejected = models.PositiveIntegerField(default=0)

    # Safety
    fraud_flag = models.BooleanField(default=False)

    # KYC / payout details (required before first withdrawal)
    id_number = models.CharField(max_length=32, blank=True)
    mpesa_number = models.CharField(max_length=20, blank=True)
    full_name = models.CharField(max_length=128, blank=True)

    # Skills
    skills = models.ManyToManyField(Skill, blank=True, related_name="workers")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Worker {self.user_id} (L{self.level})"

    @property
    def is_new_worker(self):
        from config.settings_helpers import get_new_worker_config
        threshold = get_new_worker_config()["threshold"]
        return self.completed_jobs < threshold and not self.fraud_flag


class ClientProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="client_profile",
    )
    business_name = models.CharField(max_length=128, blank=True)
    is_verified = models.BooleanField(default=False)
    auto_approved = models.BooleanField(default=False)

    # Client reputation (used in bid "past_client" score)
    avg_rating_given = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.00"),
    )
    jobs_posted = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Client {self.user_id}"

class OTPCode(models.Model):
    """
    Short-lived, single-use verification codes sent over WhatsApp.
    One row per request; validated on submit.
    """
    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Signup verification"
        LOGIN = "login", "Login verification"
        WITHDRAWAL = "withdrawal", "Withdrawal confirmation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="otp_codes",
    )
    phone = models.CharField(max_length=20)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)   # sha256 of code, never store plaintext
    code = models.CharField(max_length=10, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "consumed_at"]),
            models.Index(fields=["expires_at"]),
        ]