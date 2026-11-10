from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ledger.services import get_client_wallet, deposit_to_client
from passes.services import purchase_passes
from .models import Withdrawal, PendingPayment
from .paystack import verify_webhook_signature, verify_transaction
from .services import create_withdrawal, handle_mpesa_callback, WithdrawalError, start_client_deposit, \
    start_pass_purchase


class WithdrawalCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from fraud.services import check_rate_limit
        allowed, retry_after = check_rate_limit("withdraw", request.user.id)
        if not allowed:
            return Response(
                {"error": [f"Too many withdrawal requests. Try again in {retry_after}s."]},
                status=429,
            )
        try:
            w = create_withdrawal(
                request.user,
                amount=request.data.get("amount"),
                mpesa_number=request.data.get("mpesa_number"),
                simulate=request.data.get("simulate", False),
            )
        except (ValidationError, WithdrawalError) as e:
            return Response({"error": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "id": str(w.id),
            "status": w.status,
            "amount": str(w.amount),
            "reference": w.reference,
        }, status=status.HTTP_201_CREATED)


class WithdrawalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Withdrawal.objects.filter(user=request.user).values(
            "id", "amount", "status", "mpesa_receipt", "requested_at", "resolved_at",
        )
        return Response(list(qs))


class MpesaCallbackView(APIView):
    """Safaricom posts here. Public (no auth) — Safaricom won't send a JWT."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        kind = request.query_params.get("kind", "result")
        handle_mpesa_callback(request.data, kind=kind)
        # Safaricom expects a specific shape
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class PaystackInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        purpose = request.data.get("purpose")
        try:
            if purpose == "client_deposit":
                if request.user.role != "client":
                    return Response({"error": ["Only clients can deposit"]}, status=403)
                pp = start_client_deposit(request.user, amount_kes=request.data.get("amount_kes"))
            elif purpose == "pass_purchase":
                if request.user.role != "worker":
                    return Response({"error": ["Only workers can buy passes"]}, status=403)
                pp = start_pass_purchase(request.user, pass_count=request.data.get("pass_count"))
            else:
                return Response({"error": ["purpose must be client_deposit or pass_purchase"]}, status=400)
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)

        return Response({
            "pending_payment_id": str(pp.id),
            "reference": pp.reference,
            "amount": str(pp.amount),
            "status": pp.status,
            "authorization_url": pp.authorization_url,  # ← redirect frontend here
        }, status=201)

    permission_classes = [IsAuthenticated]

    def post(self, request):
        purpose = request.data.get("purpose")

        try:
            if purpose == "client_deposit":
                if request.user.role != "client":
                    return Response({"error": ["Only clients can deposit"]}, status=403)
                pp = start_client_deposit(
                    request.user,
                    amount_kes=request.data.get("amount_kes"),
                )
            elif purpose == "pass_purchase":
                if request.user.role != "worker":
                    return Response({"error": ["Only workers can buy passes"]}, status=403)
                pp = start_pass_purchase(
                    request.user,
                    pass_count=request.data.get("pass_count"),
                )
            else:
                return Response({"error": ["purpose must be client_deposit or pass_purchase"]}, status=400)
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)

        return Response({
            "pending_payment_id": str(pp.id),
            "reference": pp.reference,
            "amount": str(pp.amount),
            "status": pp.status,
            "message": "Check your phone for the M-Pesa prompt",
        }, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.body
        sig = request.META.get("HTTP_X_PAYSTACK_SIGNATURE", "")

        if not verify_webhook_signature(raw, sig):
            return Response({"error": "invalid signature"}, status=401)

        import json
        event = json.loads(raw)
        if event.get("event") != "charge.success":
            return Response({"ok": True})  # acknowledge non-success events

        data = event.get("data", {})
        ref = data.get("reference")
        if not ref:
            return Response({"ok": True})

        # Idempotency: already processed?
        pp = PendingPayment.objects.filter(reference=ref).first()
        if not pp:
            return Response({"ok": True})
        if pp.status == PendingPayment.Status.PAID:
            return Response({"ok": True})  # duplicate webhook

        # Verify with Paystack before crediting
        try:
            txn = verify_transaction(ref)
        except Exception:
            return Response({"ok": True})  # don't 500; Paystack will retry

        amount_received = Decimal(txn["amount"]) / 100  # cents → KES
        if amount_received != pp.amount:
            pp.status = PendingPayment.Status.FAILED
            pp.failure_reason = f"Amount mismatch: expected {pp.amount}, got {amount_received}"
            pp.resolved_at = timezone.now()
            pp.save(update_fields=["status", "failure_reason", "resolved_at"])
            return Response({"ok": True})

        # Credit the right wallet
        if pp.purpose == PendingPayment.Purpose.CLIENT_DEPOSIT:
            wallet = get_client_wallet(pp.user)
            deposit_to_client(wallet.id, amount_received, reference=ref,
                              meta={"paystack_ref": ref})
        elif pp.purpose == PendingPayment.Purpose.PASS_PURCHASE:
            purchase_passes(pp.user, pp.pass_count, reference=ref,
                            meta={"paystack_ref": ref})

        pp.status = PendingPayment.Status.PAID
        pp.resolved_at = timezone.now()
        pp.save(update_fields=["status", "resolved_at"])

        return Response({"ok": True})
