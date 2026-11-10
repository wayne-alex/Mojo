from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings

from ledger.models import Wallet, Transaction
from ledger.services import (
    _locked, _apply, get_worker_pass_wallet, get_or_create_wallet,
)
from .models import PassTier


def seed_default_tiers():
    """Run once on first migrate — idempotent."""
    if PassTier.objects.exists():
        return
    for tier in settings.MOJO_PASS_TIERS:
        PassTier.objects.create(
            name=tier["name"],
            min_budget=Decimal(tier["min_budget"]),
            max_budget=Decimal(tier["max_budget"]),
            pass_cost=tier["pass_cost"],
        )


def cost_for_budget(budget):
    """
    Tier lookup. DB override wins for MOJO_PASS_TIERS; falls back to settings.py.
    """
    from decimal import Decimal
    from django.conf import settings
    from adminpanel.services import get_setting

    tiers = get_setting("MOJO_PASS_TIERS", default=settings.MOJO_PASS_TIERS)
    b = Decimal(str(budget))
    for tier in tiers:
        if Decimal(str(tier["min_budget"])) <= b <= Decimal(str(tier["max_budget"])):
            return tier["pass_cost"]
    return 1


@transaction.atomic
def spend_bid_passes(worker, pass_cost, reference):
    """Deduct scaled pass cost before a bid is accepted into the system."""
    if pass_cost <= 0:
        return
    wallet = _locked(get_worker_pass_wallet(worker).id)
    if wallet.available_balance < pass_cost:
        raise ValidationError("Not enough passes to bid")
    _apply(wallet, "available_balance", -Decimal(pass_cost),
           Transaction.Type.PASS_DEDUCT, reference)


@transaction.atomic
def refund_passes(worker, amount, reference):
    """Refund a bid's passes (e.g. job cancelled or bid withdrawn)."""
    if amount <= 0:
        return
    wallet = _locked(get_worker_pass_wallet(worker).id)
    _apply(wallet, "available_balance", Decimal(amount),
           Transaction.Type.PASS_REFUND, reference)


@transaction.atomic
def grant_daily_passes(worker, amount, date_str):
    """Idempotent daily grant — reference embeds the date."""
    ref = f"daily_passes:{worker.id}:{date_str}"
    wallet = get_worker_pass_wallet(worker)
    if Transaction.objects.filter(wallet=wallet, reference=ref).exists():
        return False
    w = _locked(wallet.id)
    _apply(w, "available_balance", Decimal(amount),
           Transaction.Type.PASS_PURCHASE, ref,
           meta={"reason": "daily_free", "date": date_str})
    return True


@transaction.atomic
def purchase_passes(worker, amount, reference, meta=None):
    """Paid recharge. Caller debits client money via deposit_to_client first."""
    if amount <= 0:
        raise ValidationError("Purchase amount must be positive")
    w = _locked(get_worker_pass_wallet(worker).id)
    _apply(w, "available_balance", Decimal(amount),
           Transaction.Type.PASS_PURCHASE, reference, meta)