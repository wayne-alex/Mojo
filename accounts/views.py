from django.contrib.auth import authenticate, get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from .serializers import RegisterSerializer, LoginSerializer, UserSerializer
from accounts.permissions import IsAdminRole
from .models import OTPCode
User = get_user_model()


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from fraud.services import check_rate_limit, record_device, _client_ip
        ip = _client_ip(request)
        allowed, retry_after = check_rate_limit("register", ip)
        if not allowed:
            return Response(
                {"error": [f"Too many signups. Try again in {retry_after}s."]},
                status=429,
            )
        ser = RegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        try:
            record_device(user, request)
        except Exception:
            pass
        return Response(
            {
                "user": UserSerializer(user).data,
                "tokens": _tokens_for(user),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = authenticate(
            username=ser.validated_data["username"],
            password=ser.validated_data["password"],
        )
        if not user:
            return Response({"error": "Invalid credentials"},
                            status=status.HTTP_401_UNAUTHORIZED)
        return Response({
            "user": UserSerializer(user).data,
            "tokens": _tokens_for(user),
        })


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

from .otp import issue_otp, verify_otp
from .serializers import IssueOTPSerializer, VerifyOTPSerializer
from django.core.exceptions import ValidationError as DjangoValidationError


class IssueOTPView(APIView):
    """
    Authenticated user requests an OTP to their phone.
    For signup verification, the user must already be logged in (register → login → verify).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = IssueOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            otp = issue_otp(
                request.user,
                ser.validated_data["purpose"],
                phone=ser.validated_data.get("phone") or None,
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        return Response({
            "otp_id": str(otp.id),
            "expires_at": otp.expires_at,
            "purpose": otp.purpose,
        })


class VerifyOTPView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = VerifyOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            verify_otp(
                request.user,
                ser.validated_data["purpose"],
                ser.validated_data["code"],
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)

        # Side effect: marking the user verified on signup OTP
        if ser.validated_data["purpose"] == "signup":
            request.user.is_verified = True
            request.user.save(update_fields=["is_verified"])
            if request.user.role == "worker":
                # A worker's profile is_verified flag mirrors the user
                request.user.worker_profile.save()  # touched so signals fire
            elif request.user.role == "client":
                cp = request.user.client_profile
                cp.is_verified = True
                cp.save(update_fields=["is_verified"])

        return Response({"ok": True, "is_verified": request.user.is_verified})


class ResendOTPView(APIView):
    """
    Rate-limited resend. Same as issue, but throttled via fraud.check_rate_limit.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from fraud.services import check_rate_limit
        allowed, retry = check_rate_limit("otp_resend", request.user.id)
        if not allowed:
            return Response(
                {"error": [f"Slow down. Try again in {retry}s."]},
                status=429,
            )
        ser = IssueOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            otp = issue_otp(
                request.user,
                ser.validated_data["purpose"],
                phone=ser.validated_data.get("phone") or None,
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        return Response({"otp_id": str(otp.id), "expires_at": otp.expires_at})


class AdminLookupOTPView(APIView):
    """
    Admin-only: return the current active OTP for a user.
    Used when WhatsApp delivery fails and support needs to read the code
    to the user over a phone call.
    Every lookup is logged in `FraudFlag`-style audit? No — we log via
    Notification model or a dedicated table. For v1, we just log to Python
    logging so it lands in Vercel logs.
    """
    permission_classes = [IsAdminRole]

    def get(self, request):
        import logging
        logger = logging.getLogger("mojo.otp.admin_lookup")

        user_id = request.query_params.get("user_id")
        purpose = request.query_params.get("purpose", "signup")
        if not user_id:
            return Response({"error": ["user_id required"]}, status=400)

        otp = (
            OTPCode.objects
            .filter(
                user_id=user_id, purpose=purpose,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if not otp:
            return Response({"error": ["No active OTP for this user"]}, status=404)

        logger.warning(
            "ADMIN_OTP_LOOKUP actor=%s target=%s purpose=%s otp_id=%s",
            request.user.id, user_id, purpose, otp.id,
        )
        return Response({
            "otp_id": str(otp.id),
            "code": otp.code,
            "expires_at": otp.expires_at,
            "phone": otp.phone,
            "purpose": otp.purpose,
            "attempts_so_far": otp.attempts,
        })