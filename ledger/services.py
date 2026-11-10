from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Wallet, Transaction, EscrowHold


class InsufficientFunds(ValidationError):
    pass


def _locked(wallet_id):
    """Row-lock a wallet so two concurrent requests can't double-spend."""
    return Wallet.objects.select_for_update().get(pk=wallet_id)


def _apply(wallet, field, delta, txn_type, reference, meta=None):
    """Mutate a balance + write the immutable ledger row. Internal only."""
    current = getattr(wallet, field)
    new = current + delta
    if new < 0:
        raise InsufficientFunds(f"{field} would go negative on {wallet.id}")
    setattr(wallet, field, new)
    wallet.save(update_fields=[field, "updated_at"])
    Transaction.objects.create(
        wallet=wallet, type=txn_type, amount=delta,
        balance_after=new, reference=reference, meta=meta or {},
    )


# ------------------------------------------------------------------ #
# Wallet provisioning                                                 #
# ------------------------------------------------------------------ #

def get_or_create_wallet(owner, wallet_type):
    wallet, _ = Wallet.objects.get_or_create(owner=owner, type=wallet_type)
    return wallet


def get_client_wallet(owner):
    return get_or_create_wallet(owner, Wallet.Type.CLIENT)


def get_worker_earnings_wallet(owner):
    return get_or_create_wallet(owner, Wallet.Type.WORKER_EARNINGS)


def get_worker_pass_wallet(owner):
    return get_or_create_wallet(owner, Wallet.Type.WORKER_PASS)

def get_platform_wallet():
    """Return THE platform wallet (single row platform-wide)."""
    existing = Wallet.objects.filter(type=Wallet.Type.PLATFORM).first()
    if existing:
        return existing
    # fall back to lazy creation if no admin signal ran (e.g. pre-migration users)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    admin = User.objects.filter(role="admin").order_by("date_joined").first()
    if not admin:
        raise ValidationError("No admin user exists to own the platform wallet")
    return Wallet.objects.create(owner=admin, type=Wallet.Type.PLATFORM)


# ------------------------------------------------------------------ #
# Deposits                                                            #
# ------------------------------------------------------------------ #

@transaction.atomic
def deposit_to_client(client_wallet_id, amount, reference, meta=None):
    """M-Pesa / card top-up. Called after payment provider confirms."""
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Deposit must be positive")
    w = _locked(client_wallet_id)
    _apply(w, "available_balance", amount,
           Transaction.Type.DEPOSIT, reference, meta)


# ------------------------------------------------------------------ #
# Escrow lifecycle                                                    #
# ------------------------------------------------------------------ #

@transaction.atomic
def hold_escrow(client_wallet_id, amount, reference, meta=None):
    """Client available → escrow held. Call when a bid is accepted."""
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Escrow amount must be positive")
    w = _locked(client_wallet_id)
    _apply(w, "available_balance", -amount,
           Transaction.Type.ESCROW_HOLD, reference, meta)
    return EscrowHold.objects.create(
        client_wallet=w, amount=amount, reference=reference,
    )


@transaction.atomic
def release_escrow_to_worker(hold_id, worker_wallet_id, platform_fee,
                             reference, meta=None):
    """Escrow → worker pending (fee carved to platform). Approved work."""
    hold = EscrowHold.objects.select_for_update().get(pk=hold_id)
    if hold.status != EscrowHold.Status.HELD:
        raise ValidationError("Escrow already resolved")

    worker_amount = hold.amount - Decimal(platform_fee)
    if worker_amount < 0:
        raise ValidationError("Platform fee exceeds escrow amount")

    worker = _locked(worker_wallet_id)
    _apply(worker, "pending_balance", worker_amount,
           Transaction.Type.ESCROW_RELEASE, reference, meta)

    if platform_fee and Decimal(platform_fee) > 0:
        platform = _locked(get_platform_wallet().id)
        _apply(platform, "available_balance", Decimal(platform_fee),
               Transaction.Type.PLATFORM_FEE, reference, meta)

    hold.status = EscrowHold.Status.RELEASED
    hold.resolved_at = timezone.now()
    hold.save(update_fields=["status", "resolved_at"])
    return hold


@transaction.atomic
def refund_escrow_to_client(hold_id, reference, meta=None):
    """Escrow → client available. Refund or cancelled job."""
    hold = EscrowHold.objects.select_for_update().get(pk=hold_id)
    if hold.status != EscrowHold.Status.HELD:
        raise ValidationError("Escrow already resolved")
    w = _locked(hold.client_wallet_id)
    _apply(w, "available_balance", hold.amount,
           Transaction.Type.ESCROW_REFUND, reference, meta)
    hold.status = EscrowHold.Status.REFUNDED
    hold.resolved_at = timezone.now()
    hold.save(update_fields=["status", "resolved_at"])
    return hold


# ------------------------------------------------------------------ #
# Pending → available hold (called by Vercel Cron)                    #
# ------------------------------------------------------------------ #

@transaction.atomic
def clear_pending_to_available(worker_wallet_id, amount, reference):
    """Hold (24–72h) expired — pending becomes withdrawable."""
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Clear amount must be positive")
    w = _locked(worker_wallet_id)
    if w.pending_balance < amount:
        raise InsufficientFunds("Not enough pending to clear")
    _apply(w, "pending_balance", -amount,
           Transaction.Type.PENDING_TO_AVAILABLE, reference)
    _apply(w, "available_balance", amount,
           Transaction.Type.PENDING_TO_AVAILABLE, reference)


# ------------------------------------------------------------------ #
# Withdrawals                                                         #
# ------------------------------------------------------------------ #

@transaction.atomic
def request_withdrawal(worker_wallet_id, amount, reference):
    """Available → out. Then payouts app fires M-Pesa B2C."""
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Withdrawal must be positive")
    w = _locked(worker_wallet_id)
    _apply(w, "available_balance", -amount,
           Transaction.Type.WITHDRAWAL, reference)


@transaction.atomic
def refund_failed_withdrawal(worker_wallet_id, amount, reference):
    """M-Pesa B2C failed — put money back to available."""
    amount = Decimal(amount)
    w = _locked(worker_wallet_id)
    _apply(w, "available_balance", amount,
           Transaction.Type.WITHDRAWAL_REFUND, reference)

@transaction.atomic
def split_escrow(hold_id, client_share, worker_wallet_id, worker_share,
                 platform_fee, reference, meta=None):
    """
    Escrow → split between client refund and worker payout.
    client_share + worker_share + platform_fee should equal hold.amount.
    """
    hold = EscrowHold.objects.select_for_update().get(pk=hold_id)
    if hold.status != EscrowHold.Status.HELD:
        raise ValidationError("Escrow already resolved")

    client_share = Decimal(client_share)
    worker_share = Decimal(worker_share)
    platform_fee = Decimal(platform_fee)
    total = client_share + worker_share + platform_fee
    if total != hold.amount:
        raise ValidationError(
            f"Split sums to {total} but escrow holds {hold.amount}"
        )

    if client_share > 0:
        cw = _locked(hold.client_wallet_id)
        _apply(cw, "available_balance", client_share,
               Transaction.Type.ESCROW_REFUND, reference, meta)
    if worker_share > 0:
        ww = _locked(worker_wallet_id)
        _apply(ww, "pending_balance", worker_share,
               Transaction.Type.ESCROW_RELEASE, reference, meta)
    if platform_fee > 0:
        pw = _locked(get_platform_wallet().id)
        _apply(pw, "available_balance", platform_fee,
               Transaction.Type.PLATFORM_FEE, reference, meta)

    hold.status = EscrowHold.Status.SPLIT
    hold.resolved_at = timezone.now()
    hold.save(update_fields=["status", "resolved_at"])
    return hold