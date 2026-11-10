from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from jobs.services import run_auto_approve_batch, run_pending_clear_batch


def _check_secret(request):
    return (
        request.headers.get("x-vercel-cron") == "1"
        or request.headers.get("Authorization") == f"Bearer {settings.CRON_SECRET}"
    )
class CronAutoApproveView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        if not _check_secret(request):
            return JsonResponse({"error": "forbidden"}, status=403)
        count = run_auto_approve_batch()
        return JsonResponse({"auto_approved": count})


class CronReleaseHoldsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        if not _check_secret(request):
            return JsonResponse({"error": "forbidden"}, status=403)
        count = run_pending_clear_batch()
        return JsonResponse({"cleared": count})

class CronPurgeOTPsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        if not _check_secret(request):
            return JsonResponse({"error": "forbidden"}, status=403)
        from accounts.models import OTPCode
        cutoff = timezone.now() - timedelta(days=7)
        deleted, _ = OTPCode.objects.filter(created_at__lte=cutoff).delete()
        return JsonResponse({"deleted": deleted})