import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class Rating(models.Model):
    class Direction(models.TextChoices):
        CLIENT_TO_WORKER = "c2w", "Client → Worker"
        WORKER_TO_CLIENT = "w2c", "Worker → Client"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "jobs.Job", on_delete=models.CASCADE, related_name="ratings",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ratings_given",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ratings_received",
    )
    direction = models.CharField(max_length=3, choices=Direction.choices)
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("job", "author")]
        indexes = [
            models.Index(fields=["subject", "direction"]),
            models.Index(fields=["job"]),
        ]

    def __str__(self):
        return f"{self.direction} {self.score}/5 on {self.job_id}"