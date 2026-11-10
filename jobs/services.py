from decimal import Decimal
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth import get_user_model

from accounts.models import WorkerProfile
from ledger.models import EscrowHold, Transaction
from ledger.services import (
    hold_escrow,
    release_escrow_to_worker,
    refund_escrow_to_client,
    clear_pending_to_available,
    get_client_wallet,
    get_worker_earnings_wallet,
)
from passes.services import spend_bid_passes, refund_passes, cost_for_budget
from .models import Job, Bid
from .scoring import score_bid
from notifications.services import notify
from notifications.models import Notification
from fraud.services import sanitize_message

User = get_user_model()


class JobStateError(ValidationError):
    pass


# ------------------------------------------------------------------ #
# Step 1: client posts a job                                          #
# ------------------------------------------------------------------ #

@transaction.atomic
def post_job(
    client,
    *,
    title,
    description,
    deadline,
    budget_min,
    budget_max,
    min_level=1,
    required_skill_ids=None,
    bid_window_hours=48,
    max_bids=50,
):
    if client.role != "client":
        raise ValidationError("Only clients can post jobs")

    budget_min = Decimal(budget_min)
    budget_max = Decimal(budget_max)
    if budget_min > budget_max:
        raise ValidationError("budget_min must be <= budget_max")

    job = Job.objects.create(
        client=client,
        title=title,
        description=description,
        deadline=deadline,
        budget_min=budget_min,
        budget_max=budget_max,
        min_level=min_level,
        bid_window_ends_at=timezone.now() + timedelta(hours=bid_window_hours),
        max_bids=max_bids,
        pass_cost=cost_for_budget(budget_max),
        status=Job.Status.OPEN,
    )

    if required_skill_ids:
        job.required_skills.set(required_skill_ids)

    return job


# ------------------------------------------------------------------ #
# Step 2–3: worker places a bid (charges passes)                      #
# ------------------------------------------------------------------ #

@transaction.atomic
def place_bid(worker, job_id, *, price, delivery_days, message=""):
    job = Job.objects.select_for_update().get(pk=job_id)

    if not job.is_biddable():
        raise JobStateError("Job is not accepting bids")

    wprofile = getattr(worker, "worker_profile", None)
    if not wprofile:
        raise ValidationError("Worker has no profile")
    if wprofile.fraud_flag:
        raise ValidationError("Account is restricted")
    if wprofile.level < job.min_level:
        raise ValidationError(f"Requires level {job.min_level}")

    if Bid.objects.filter(job=job, worker=worker).exists():
        raise ValidationError("You already have a bid on this job")

    price = Decimal(price)
    if price <= 0:
        raise ValidationError("Price must be positive")
    if price > job.budget_max:
        raise ValidationError("Bid price exceeds client budget")

    # Reject phone numbers / links until job is accepted
    sanitize_message(message, allow_contact=False)

    ref = f"bid:{job.id}:{worker.id}"
    spend_bid_passes(worker, job.pass_cost, ref)

    bid = Bid.objects.create(
        job=job,
        worker=worker,
        price=price,
        delivery_days=delivery_days,
        message=message,
        pass_reference=ref,
    )

    # Score immediately so the top-3 view has data
    total, breakdown = score_bid(bid, job)
    bid.score_total = total
    bid.score_breakdown = breakdown
    bid.save(update_fields=["score_total", "score_breakdown"])

    # Atomic counter bump (F() only works with queryset .update(), not save())
    Job.objects.filter(pk=job.pk).update(bid_count=models.F("bid_count") + 1)
    job.refresh_from_db(fields=["bid_count"])

    return bid


# ------------------------------------------------------------------ #
# Step 4–6: client accepts a bid (money to escrow, worker starts)     #
# ------------------------------------------------------------------ #

@transaction.atomic
def accept_bid(client, job_id, bid_id):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.client_id != client.id:
        raise ValidationError("Not your job")
    if job.status != Job.Status.OPEN:
        raise JobStateError(f"Cannot accept bid in status {job.status}")

    bid = Bid.objects.select_for_update().get(pk=bid_id, job=job)
    if bid.status != Bid.Status.SUBMITTED:
        raise JobStateError("Bid is no longer available")

    agreed = bid.price
    escrow_ref = f"job:{job.id}"

    hold_escrow(
        client_wallet_id=get_client_wallet(client).id,
        amount=agreed,
        reference=escrow_ref,
        meta={"job_id": str(job.id), "bid_id": str(bid.id)},
    )

    bid.status = Bid.Status.ACCEPTED
    bid.save(update_fields=["status"])

    # Reject all other submitted bids on this job; capture worker ids first
    rejected_qs = job.bids.exclude(pk=bid.pk).filter(status=Bid.Status.SUBMITTED)
    rejected_worker_ids = list(rejected_qs.values_list("worker_id", flat=True))
    rejected_qs.update(status=Bid.Status.REJECTED)

    job.accepted_bid = bid
    job.agreed_price = agreed
    job.status = Job.Status.IN_PROGRESS
    job.save(update_fields=["accepted_bid", "agreed_price", "status"])

    # Side-effect notifications AFTER state is committed
    try:
        notify(bid.worker, kind=Notification.Kind.BID_ACCEPTED,
               title="You got the job!",
               body=f"{job.title} — deliver by {job.deadline:%Y-%m-%d}",
               link=f"/jobs/{job.id}", reference=str(job.id))
        for wid in rejected_worker_ids:
            try:
                rw = User.objects.get(pk=wid)
            except User.DoesNotExist:
                continue
            notify(rw, kind=Notification.Kind.BID_LOST,
                   title="Bid not selected",
                   body=f"Your bid on '{job.title}' was not chosen.",
                   link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass  # notifications must never break the transaction

    return job, bid


# ------------------------------------------------------------------ #
# Step 7: worker delivers                                             #
# ------------------------------------------------------------------ #

@transaction.atomic
def deliver(job_id, worker, *, delivery_text="", delivery_file_url=""):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.status != Job.Status.IN_PROGRESS:
        raise JobStateError(f"Cannot deliver in status {job.status}")
    if not job.accepted_bid or job.accepted_bid.worker_id != worker.id:
        raise ValidationError("Not your job to deliver")

    now = timezone.now()
    job.delivery_text = delivery_text
    job.delivery_file_url = delivery_file_url
    job.delivered_at = now
    from config.settings_helpers import get_auto_approve_days
    auto_days = get_auto_approve_days()
    job.auto_approve_at = now + timedelta(days=auto_days)
    job.status = Job.Status.DELIVERED
    job.save(update_fields=[
        "delivery_text",
        "delivery_file_url",
        "delivered_at",
        "auto_approve_at",
        "status",
    ])

    try:
        notify(job.client, kind=Notification.Kind.DELIVERED,
               title="Worker delivered",
               body=f"{job.title} is ready for review.",
               link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass

    return job


# ------------------------------------------------------------------ #
# Step 8–9: client approves → escrow releases to worker pending       #
# ------------------------------------------------------------------ #

@transaction.atomic
def approve(job_id, actor, *, is_auto=False):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.status != Job.Status.DELIVERED:
        raise JobStateError(f"Cannot approve in status {job.status}")
    if not is_auto and job.client_id != actor.id:
        raise ValidationError("Not your job to approve")

    worker = job.accepted_bid.worker
    from config.settings_helpers import get_platform_fee_pct
    fee_pct = get_platform_fee_pct()
    platform_fee = (job.agreed_price * fee_pct).quantize(Decimal("0.01"))

    hold = EscrowHold.objects.get(
        reference=f"job:{job.id}", status=EscrowHold.Status.HELD,
    )

    release_escrow_to_worker(
        hold_id=hold.id,
        worker_wallet_id=get_worker_earnings_wallet(worker).id,
        platform_fee=platform_fee,
        reference=f"payout:{job.id}",
        meta={"job_id": str(job.id), "auto": is_auto},
    )

    job.status = Job.Status.COMPLETED
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "completed_at"])

    # Atomic counter bump — never use F() inside save(update_fields)
    WorkerProfile.objects.filter(pk=worker.worker_profile.pk).update(
        completed_jobs=models.F("completed_jobs") + 1,
    )

    try:
        notify(worker, kind=Notification.Kind.APPROVED,
               title="Payment released",
               body=(
                   f"{job.title} approved. Funds move to your available "
                   f"balance in {settings.MOJO_PENDING_HOLD_HOURS}h."
               ),
               link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass

    return job


# ------------------------------------------------------------------ #
# Step 9 (cont.): client requests a revision (hard cap 2)             #
# ------------------------------------------------------------------ #

@transaction.atomic
def request_revision(job_id, client, *, feedback=""):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.client_id != client.id:
        raise ValidationError("Not your job")
    if job.status != Job.Status.DELIVERED:
        raise JobStateError("Only delivered jobs can be revised")
    if not job.can_revise():
        raise JobStateError("Revision cap reached")

    job.revisions_used += 1
    job.status = Job.Status.IN_PROGRESS
    job.delivered_at = None
    job.auto_approve_at = None
    job.save(update_fields=[
        "revisions_used",
        "status",
        "delivered_at",
        "auto_approve_at",
    ])

    try:
        notify(job.accepted_bid.worker, kind=Notification.Kind.REVISION_REQUESTED,
               title="Revision requested",
               body=f"{job.title}: {feedback or 'See job for details.'}",
               link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass

    return job


# ------------------------------------------------------------------ #
# Cancel a job in DRAFT / OPEN (no escrow yet)                        #
# ------------------------------------------------------------------ #

@transaction.atomic
def cancel_job(job_id, actor):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.client_id != actor.id:
        raise ValidationError("Not your job")
    if job.status not in (Job.Status.DRAFT, Job.Status.OPEN):
        raise JobStateError("Only draft/open jobs can be cancelled")

    # Refund passes to still-submitted bidders
    for bid in job.bids.filter(status=Bid.Status.SUBMITTED):
        refund_passes(bid.worker, job.pass_cost, f"refund:bid:{bid.id}")
        bid.status = Bid.Status.WITHDRAWN
        bid.save(update_fields=["status"])

    job.status = Job.Status.CANCELLED
    job.cancelled_at = timezone.now()
    job.save(update_fields=["status", "cancelled_at"])
    return job


# ------------------------------------------------------------------ #
# Cron: auto-approve jobs past their 5-day window (decision #5)       #
# ------------------------------------------------------------------ #

def find_jobs_due_for_auto_approve():
    return Job.objects.filter(
        status=Job.Status.DELIVERED,
        auto_approve_at__lte=timezone.now(),
    )


def run_auto_approve_batch():
    count = 0
    for job in find_jobs_due_for_auto_approve():
        try:
            approve(job.id, actor=None, is_auto=True)
            count += 1
        except JobStateError:
            continue
    return count


# ------------------------------------------------------------------ #
# Cron: pending → available after hold (decision #6)                  #
# ------------------------------------------------------------------ #

def find_pending_clears_due(hours_hold):
    cutoff = timezone.now() - timedelta(hours=hours_hold)
    return Transaction.objects.filter(
        type=Transaction.Type.ESCROW_RELEASE,
        created_at__lte=cutoff,
        cleared=False,
    ).select_related("wallet")


def run_pending_clear_batch(hours_hold=None):
    if hours_hold is None:
        from config.settings_helpers import get_pending_hold_hours
        hours_hold = get_pending_hold_hours()

    cleared = 0
    for txn in find_pending_clears_due(hours_hold):
        clear_pending_to_available(
            worker_wallet_id=txn.wallet_id,
            amount=txn.amount,
            reference=f"clear:{txn.id}",
        )
        txn.cleared = True
        txn.save(update_fields=["cleared"])
        cleared += 1
    return cleared