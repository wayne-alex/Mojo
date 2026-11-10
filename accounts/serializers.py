from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .models import WorkerProfile, ClientProfile, Skill

User = get_user_model()


# ------------------------------------------------------------------ #
# Read serializers                                                    #
# ------------------------------------------------------------------ #

class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "name"]


class WorkerProfileSerializer(serializers.ModelSerializer):
    skills = SkillSerializer(many=True, read_only=True)

    class Meta:
        model = WorkerProfile
        fields = [
            "level", "accuracy_score", "avg_rating", "completion_rate",
            "completed_jobs", "fraud_flag", "full_name", "id_number",
            "mpesa_number", "skills", "is_new_worker",
        ]
        read_only_fields = [
            "level", "accuracy_score", "avg_rating", "completion_rate",
            "completed_jobs", "fraud_flag", "is_new_worker",
        ]


class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = ["business_name", "is_verified", "auto_approved",
                  "avg_rating_given", "jobs_posted"]
        read_only_fields = ["is_verified", "auto_approved",
                            "avg_rating_given", "jobs_posted"]


class UserSerializer(serializers.ModelSerializer):
    worker_profile = WorkerProfileSerializer(read_only=True)
    client_profile = ClientProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "phone", "email", "role",
                  "is_verified", "worker_profile", "client_profile",
                  "date_joined"]
        read_only_fields = ["id", "role", "is_verified", "date_joined"]


# ------------------------------------------------------------------ #
# Registration                                                        #
# ------------------------------------------------------------------ #

class RegisterSerializer(serializers.Serializer):
    """
    A single endpoint handles both roles, gated by `role`.
    - Workers require `phone` (OTP is a later step — user.is_verified stays False)
    - Clients require either `phone` or `email`
    """
    role = serializers.ChoiceField(choices=["worker", "client"])
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)

    # Client-only
    business_name = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        role = attrs["role"]
        if role == "worker" and not attrs.get("phone"):
            raise serializers.ValidationError({"phone": "Workers must sign up with a phone number."})
        if role == "client" and not (attrs.get("phone") or attrs.get("email")):
            raise serializers.ValidationError(
                {"phone": "Provide either a phone or an email."}
            )

        if User.objects.filter(username=attrs["username"]).exists():
            raise serializers.ValidationError({"username": "Already taken."})
        if attrs.get("phone") and User.objects.filter(phone=attrs["phone"]).exists():
            raise serializers.ValidationError({"phone": "Already registered."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data["role"]
        password = validated_data.pop("password")
        business_name = validated_data.pop("business_name", "")

        user = User.objects.create_user(
            username=validated_data["username"],
            password=password,
            role=role,
            phone=validated_data.get("phone") or None,
            email=validated_data.get("email") or "",
        )

        # The signal creates profile + wallets. Optionally fill extras.
        if role == "client" and business_name:
            user.client_profile.business_name = business_name
            user.client_profile.save(update_fields=["business_name"])

        return user


# ------------------------------------------------------------------ #
# Login                                                               #
# ------------------------------------------------------------------ #

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

class IssueOTPSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(
        choices=["signup", "login", "withdrawal"], default="signup",
    )
    phone = serializers.CharField(required=False, allow_blank=True)


class VerifyOTPSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(
        choices=["signup", "login", "withdrawal"], default="signup",
    )
    code = serializers.CharField(max_length=10)