from decimal import Decimal
from datetime import timezone as tz

from rest_framework import serializers
from django.utils import timezone

from accounts.models import Skill
from .models import Job, Bid


# ------------------------------------------------------------------ #
# Nested read helpers                                                 #
# ------------------------------------------------------------------ #

class SkillInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "name"]


class BidReadSerializer(serializers.ModelSerializer):
    worker_username = serializers.CharField(source="worker.username", read_only=True)
    worker_level = serializers.IntegerField(
        source="worker.worker_profile.level", read_only=True, default=None,
    )
    worker_rating = serializers.DecimalField(
        source="worker.worker_profile.avg_rating", max_digits=3, decimal_places=2,
        read_only=True, default=None,
    )
    worker_completed = serializers.IntegerField(
        source="worker.worker_profile.completed_jobs", read_only=True, default=None,
    )

    class Meta:
        model = Bid
        fields = [
            "id", "worker_username", "worker_level", "worker_rating",
            "worker_completed", "price", "delivery_days", "message",
            "score_total", "status", "created_at",
        ]


class JobSerializer(serializers.ModelSerializer):
    client_username = serializers.CharField(source="client.username", read_only=True)
    required_skills = SkillInlineSerializer(many=True, read_only=True)
    bid_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "title", "description", "deadline",
            "budget_min", "budget_max", "min_level", "required_skills",
            "status", "bid_window_ends_at", "bid_count", "pass_cost",
            "agreed_price", "revisions_used", "delivered_at",
            "auto_approve_at", "completed_at", "created_at",
            "client_username",
        ]


# ------------------------------------------------------------------ #
# Create / action                                                     #
# ------------------------------------------------------------------ #

class JobCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    deadline = serializers.DateTimeField()
    budget_min = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    budget_max = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    min_level = serializers.IntegerField(min_value=1, max_value=10, default=1)
    required_skill_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )
    bid_window_hours = serializers.IntegerField(min_value=1, max_value=720, default=48)
    max_bids = serializers.IntegerField(min_value=1, max_value=500, default=50)

    def validate(self, attrs):
        if attrs["budget_min"] > attrs["budget_max"]:
            raise serializers.ValidationError(
                {"budget_min": "Must be <= budget_max"}
            )
        if attrs["deadline"] <= timezone.now():
            raise serializers.ValidationError(
                {"deadline": "Deadline must be in the future"}
            )
        return attrs


class BidCreateSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    delivery_days = serializers.IntegerField(min_value=1, max_value=365)
    message = serializers.CharField(required=False, allow_blank=True, default="")


class BidFeedSerializer(BidReadSerializer):
    """What a client sees on top-3 — includes the score breakdown."""
    score_breakdown = serializers.JSONField(read_only=True)

    class Meta(BidReadSerializer.Meta):
        fields = BidReadSerializer.Meta.fields + ["score_breakdown"]


# ------------------------------------------------------------------ #
# Job feed (worker view) — annotated for UI                           #
# ------------------------------------------------------------------ #

class JobFeedRowSerializer(JobSerializer):
    locked = serializers.BooleanField(read_only=True)
    lock_reason = serializers.CharField(read_only=True, allow_null=True)
    already_bid = serializers.BooleanField(read_only=True)
    can_bid = serializers.BooleanField(read_only=True)