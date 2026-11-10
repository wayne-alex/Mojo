from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, WorkerProfile, ClientProfile
from accounts.permissions import IsAdminRole
from ledger.models import Wallet, EscrowHold, Transaction
from jobs.models import Job, Bid
from disputes.models import Dispute
from fraud.models import FraudFlag
from notifications.models import Notification


class DashboardView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        escrow_total = (
            EscrowHold.objects
            .filter(status=EscrowHold.Status.HELD)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        fees_total = (
            Transaction.objects
            .filter(type=Transaction.Type.PLATFORM_FEE)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        pending_payouts = (
            Wallet.objects
            .filter(type=Wallet.Type.WORKER_EARNINGS)
            .aggregate(s=Sum("pending_balance"))["s"] or Decimal("0.00")
        )
        available_payouts = (
            Wallet.objects
            .filter(type=Wallet.Type.WORKER_EARNINGS)
            .aggregate(s=Sum("available_balance"))["s"] or Decimal("0.00")
        )

        return Response({
            "escrow_held_total": str(escrow_total),
            "fees_earned_total": str(fees_total),
            "payouts_pending": str(pending_payouts),
            "payouts_available": str(available_payouts),
            "active_jobs": Job.objects.filter(
                status__in=[Job.Status.OPEN, Job.Status.IN_PROGRESS, Job.Status.DELIVERED],
            ).count(),
            "open_disputes": Dispute.objects.filter(
                status__in=[Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW],
            ).count(),
            "fraud_flags_open": FraudFlag.objects.count(),
            "users": {
                "workers": User.objects.filter(role="worker").count(),
                "clients": User.objects.filter(role="client").count(),
            },
        })


class RevenueView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        # Fees by month (last 12 months)
        rows = (
            Transaction.objects
            .filter(type=Transaction.Type.PLATFORM_FEE)
            .extra(select={"month": "strftime('%%Y-%%m', created_at)"})
            .values("month")
            .annotate(amount=Sum("amount"))
            .order_by("month")
        )
        pass_sales = (
            Transaction.objects
            .filter(type=Transaction.Type.PASS_PURCHASE)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        total_fees = (
            Transaction.objects
            .filter(type=Transaction.Type.PLATFORM_FEE)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        return Response({
            "fees_by_month": [
                {"month": r["month"], "amount": str(r["amount"])} for r in rows
            ],
            "pass_sales_lifetime": str(pass_sales),
            "total_fees_lifetime": str(total_fees),
        })


class DisputeQueueView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        qs = (
            Dispute.objects
            .filter(status__in=[Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW])
            .order_by("created_at")
            .values(
                "id", "job_id", "opened_by_id", "reason",
                "status", "created_at",
            )
        )
        return Response({"count": qs.count(), "results": list(qs)})


class SettingsListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        from .models import Setting
        rows = Setting.objects.all().values(
            "key", "value", "value_type", "description", "updated_at",
        )
        return Response({"results": list(rows)})