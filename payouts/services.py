import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import WorkerProfile
from ledger.services import (
    request_withdrawal, refund_failed_withdrawal, get_worker_earnings_wallet,
)
from notifications.models import Notification
from notifications.services import notify
from . import mpesa, paystack
from .models import Withdrawal, PendingPayment


class WithdrawalError(ValidationError):
    pass


MIN_WITHDRAWAL = Decimal("1.00")


@transaction.atomic
def create_withdrawal(user, *, amount, mpesa_number=None, simulate=False):
    """Step 1: worker requests a withdrawal. Money leaves 'available'."""
    if user.role != "worker":
        raise ValidationError("Only workers can withdraw")

    wp = WorkerProfile.objects.select_for_update().get(user=user)
    if wp.fraud_flag:
        raise ValidationError("Account is restricted")
    if not wp.id_number or not wp.mpesa_number:
        raise ValidationError("Complete KYC (ID + M-Pesa number) before withdrawing")

    amount = Decimal(amount)
    if amount < MIN_WITHDRAWAL:
        raise ValidationError(f"Minimum withdrawal is {MIN_WITHDRAWAL}")
    if not mpesa_number:
        mpesa_number = wp.mpesa_number

    ref = f"payout:{uuid.uuid4()}"
    wallet = get_worker_earnings_wallet(user)

    # Move money out of available FIRST (ledger step)
    request_withdrawal(wallet.id, amount, ref)

    w = Withdrawal.objects.create(
        user=user, amount=amount, mpesa_number=mpesa_number,
        reference=ref, status=Withdrawal.Status.REQUESTED,
    )

    if simulate or not mpesa.is_configured():
        # Local/dev path: mark as paid immediately
        w.status = Withdrawal.Status.PAID
        w.resolved_at = timezone.now()
        w.mpesa_receipt = "SIMULATED"
        w.save(update_fields=["status", "resolved_at", "mpesa_receipt"])
        return w

    # Real path: fire B2C, status stays REQUESTED/awaiting callback
    try:
        result = mpesa.initiate_b2c(
            phone=mpesa_number, amount=amount,
            remarks="Mojo payout", reference=ref,
        )
        w.conversation_id = result["conversation_id"]
        w.originator_conversation_id = result["originator_conversation_id"]
        w.status = Withdrawal.Status.PROCESSING
        w.processing_at = timezone.now()
        w.save(update_fields=[
            "conversation_id", "originator_conversation_id",
            "status", "processing_at",
        ])
    except Exception as exc:
        # Immediate failure — put money back
        refund_failed_withdrawal(wallet.id, amount, f"refund:{ref}")
        w.status = Withdrawal.Status.FAILED
        w.failure_reason = str(exc)
        w.resolved_at = timezone.now()
        w.save(update_fields=["status", "failure_reason", "resolved_at"])
        raise WithdrawalError(f"Payout failed: {exc}") from exc
    try:
        notify(user, kind=Notification.Kind.WITHDRAWAL_PAID,
               title="Withdrawal paid",
               body=f"{amount} sent to {mpesa_number}.",
               link="/wallet", reference=ref)
    except Exception:
        pass
    return w


@transaction.atomic
def handle_mpesa_callback(payload, kind="result"):
    """
    Called by Safaricom. Idempotent: safe to receive the same callback twice.
    `kind` is either "result" (final) or "timeout".
    """
    result = payload.get("Result", {})
    conv_id = result.get("ConversationID") or payload.get("ConversationID")
    originator_id = result.get("OriginatorConversationID") or payload.get("OriginatorConversationID")

    w = (
            Withdrawal.objects.select_for_update()
            .filter(
                conversation_id=conv_id or "__no_match__",
            )
            .first()
            or Withdrawal.objects.select_for_update()
            .filter(originator_conversation_id=originator_id or "__no_match__")
            .first()
    )
    if not w:
        return None

    if w.status in (Withdrawal.Status.PAID, Withdrawal.Status.FAILED):
        return w  # already resolved

    result_code = int(result.get("ResultCode", -1))
    if kind == "timeout" or result_code != 0:
        # Failure — refund available
        refund_failed_withdrawal(
            get_worker_earnings_wallet(w.user).id,
            w.amount,
            f"refund:{w.reference}",
        )
        w.status = Withdrawal.Status.FAILED
        w.failure_reason = result.get("ResultDesc", "Callback failure")
        w.resolved_at = timezone.now()
        w.save(update_fields=["status", "failure_reason", "resolved_at"])
    else:
        # Success — note receipt number
        params = result.get("ResultParameters", {}).get("ResultParameter", []) or []
        receipt = ""
        for p in params:
            if p.get("Key") == "TransactionReceipt":
                receipt = p.get("Value", "")
                break
        w.status = Withdrawal.Status.PAID
        w.mpesa_receipt = receipt
        w.resolved_at = timezone.now()
        w.save(update_fields=["status", "mpesa_receipt", "resolved_at"])
    if w.status == Withdrawal.Status.FAILED:
        try:
            notify(w.user, kind=Notification.Kind.WITHDRAWAL_FAILED,
                   title="Withdrawal failed",
                   body=f"{w.amount}: callback reported failure. Funds returned.",
                   link="/wallet", reference=w.reference)
        except Exception:
            pass
    elif w.status == Withdrawal.Status.PAID:
        try:
            notify(w.user, kind=Notification.Kind.WITHDRAWAL_PAID,
                   title="Withdrawal paid",
                   body=f"{w.amount} sent. Receipt {w.mpesa_receipt or 'pending'}.",
                   link="/wallet", reference=w.reference)
        except Exception:
            pass
    return w


PASS_PRICE_KES = Decimal(str(getattr(settings, "PASS_PRICE_KES", "10")))


@transaction.atomic
def start_client_deposit(user, *, amount_kes):
    """Create PendingPayment + initialize Paystack transaction for a wallet top-up."""
    amount = Decimal(str(amount_kes))
    if amount < Decimal("10.00"):
        raise ValidationError("Minimum deposit is KES 10")

    ref = f"deposit-{uuid.uuid4()}"
    pp = PendingPayment.objects.create(
        user=user,
        purpose=PendingPayment.Purpose.CLIENT_DEPOSIT,
        amount=amount,
        reference=ref,
    )

    try:
        result = paystack.initialize_transaction(
            email=user.email,
            phone=user.phone,
            amount_kes=amount,
            reference=ref,
            metadata={
                "purpose": "client_deposit",
                "user_id": str(user.id),
            },
            callback_url=settings.PAYSTACK_CALLBACK_URL,
        )
    except paystack.PaystackError as exc:
        pp.status = PendingPayment.Status.FAILED
        pp.failure_reason = str(exc)
        pp.resolved_at = timezone.now()
        pp.save(update_fields=["status", "failure_reason", "resolved_at"])
        raise ValidationError(f"Payment initiation failed: {exc}") from exc

    pp.provider_response = result
    pp.save(update_fields=["provider_response"])
    return pp


@transaction.atomic
def start_pass_purchase(worker, *, pass_count):
    """Create PendingPayment + initialize Paystack transaction for a pass bundle."""
    count = int(pass_count)
    if count < 1 or count > 500:
        raise ValidationError("Pass count must be between 1 and 500")

    amount = (PASS_PRICE_KES * count).quantize(Decimal("0.01"))
    ref = f"passes-{uuid.uuid4()}"

    pp = PendingPayment.objects.create(
        user=worker,
        purpose=PendingPayment.Purpose.PASS_PURCHASE,
        amount=amount,
        pass_count=count,
        reference=ref,
    )

    try:
        result = paystack.initialize_transaction(
            email=worker.email,
            phone=worker.phone,
            amount_kes=amount,
            reference=ref,
            metadata={
                "purpose": "pass_purchase",
                "user_id": str(worker.id),
                "pass_count": count,
            },
            callback_url=settings.PAYSTACK_CALLBACK_URL,
        )
    except paystack.PaystackError as exc:
        pp.status = PendingPayment.Status.FAILED
        pp.failure_reason = str(exc)
        pp.resolved_at = timezone.now()
        pp.save(update_fields=["status", "failure_reason", "resolved_at"])
        raise ValidationError(f"Payment initiation failed: {exc}") from exc

    pp.provider_response = result
    pp.save(update_fields=["provider_response"])
    return pp
