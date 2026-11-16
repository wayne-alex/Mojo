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
def deliver(job_id, worker, *, delivery_text="", delivery_file=None):
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.status != Job.Status.IN_PROGRESS:
        raise JobStateError(f"Cannot deliver in status {job.status}")
    if not job.accepted_bid or job.accepted_bid.worker_id != worker.id:
        raise ValidationError("Not your job to deliver")

    now = timezone.now()
    job.delivery_text = delivery_text
    if delivery_file:
        job.delivery_file = delivery_file
    job.delivered_at = now
    job.auto_approve_at = now + timedelta(days=settings.MOJO_AUTO_APPROVE_DAYS)
    job.status = Job.Status.DELIVERED
    job.save(update_fields=[
        "delivery_text", "delivery_file", "delivered_at",
        "auto_approve_at", "status",
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

# ------------------------------------------------------------------ #
# Survey submission with anti-bot validation                         #
# ------------------------------------------------------------------ #

@transaction.atomic
def submit_survey(job_id, worker, *, answers: dict):
    """
    Validate survey answers against `survey_questions`. Each question
    must have a `correct_answer` field for scoring. If accuracy < 60%,
    the submission is rejected (bot detection).
    """
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.job_type != Job.JobType.SURVEY:
        raise ValidationError("This job is not a survey")
    if job.status != Job.Status.IN_PROGRESS:
        raise JobStateError(f"Cannot submit survey in status {job.status}")
    if not job.accepted_bid or job.accepted_bid.worker_id != worker.id:
        raise ValidationError("Not your job to submit")

    questions = job.survey_questions or []
    if not questions:
        raise ValidationError("No survey questions defined")

    correct = 0
    total = len(questions)
    for q in questions:
        qid = str(q["id"])
        user_answer = answers.get(qid)
        expected = q.get("correct_answer")
        if expected and user_answer and str(user_answer).strip().lower() == str(expected).strip().lower():
            correct += 1

    accuracy = (correct / total) * 100 if total else 0

    # Anti-bot: reject if accuracy is too low
    if accuracy < 60:
        raise ValidationError(
            f"Survey accuracy too low ({accuracy:.0f}%). Bot-like behavior detected. "
            "Your submission was rejected."
        )

    now = timezone.now()
    job.survey_answers = answers
    job.delivery_text = f"Survey submitted. Score: {correct}/{total} ({accuracy:.0f}%)"
    job.delivered_at = now
    job.auto_approve_at = now + timedelta(days=settings.MOJO_AUTO_APPROVE_DAYS)
    job.status = Job.Status.DELIVERED
    job.save(update_fields=[
        "survey_answers", "delivery_text", "delivered_at",
        "auto_approve_at", "status",
    ])

    try:
        notify(job.client, kind=Notification.Kind.DELIVERED,
               title="Survey submitted",
               body=f"{job.title} — accuracy {accuracy:.0f}%. Review to approve.",
               link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass

    return job


# ------------------------------------------------------------------ #
# AI Content Check (costs 10 KES, deducts from client wallet)        #
# ------------------------------------------------------------------ #

@transaction.atomic
def check_ai_score(job_id, client):
    """
    Deduct 10 KES from the client's wallet, analyze the delivery file,
    and store the AI score on the job.
    """
    import hashlib
    from ledger.services import (
        get_client_wallet, get_platform_wallet, _locked, _apply,
    )
    from ledger.models import Transaction

    job = Job.objects.select_for_update().get(pk=job_id)
    if job.client_id != client.id:
        raise ValidationError("Not your job")
    if job.status not in (Job.Status.DELIVERED,):
        raise JobStateError("Can only check AI on delivered jobs")
    if job.ai_score is not None:
        raise ValidationError("AI check already performed for this job")

    # Deduct 10 bob from client wallet
    price = Decimal(str(settings.AI_CHECK_PRICE_KES))
    wallet = _locked(get_client_wallet(client).id)
    if wallet.available_balance < price:
        raise ValidationError(f"Insufficient balance. Need KES {price} for AI check.")

    ref = f"ai_check:{job.id}"
    _apply(wallet, "available_balance", -price,
           Transaction.Type.ADJUSTMENT, ref,
           meta={"reason": "ai_detection_fee", "job_id": str(job.id)})

    # Extract text from the delivery file (simplified: read bytes)
    text_sample = ""
    if job.delivery_file:
        try:
            job.delivery_file.open()
            raw = job.delivery_file.read()
            text_sample = raw.decode("utf-8", errors="ignore")[:5000]
        except Exception:
            text_sample = ""
    if not text_sample and job.delivery_text:
        text_sample = job.delivery_text[:5000]

    # Fake AI detection (deterministic by hash) — swap for real API later
    if settings.AI_DETECTION_API_KEY:
        # Real call placeholder — implement with your chosen provider
        score = _call_ai_detector(text_sample)
    else:
        # Deterministic score from content hash (0–100)
        h = hashlib.sha256(text_sample.encode()).hexdigest()
        score = Decimal(str(int(h[:4], 16) % 100))

    job.ai_score = score
    job.save(update_fields=["ai_score"])
    return job


def _call_ai_detector(text: str) -> Decimal:
    """Placeholder — plug in a real AI detection API here (GPTZero, Originality.ai, etc.)."""
    # For now, deterministic based on content hash
    import hashlib
    h = hashlib.sha256(text.encode()).hexdigest()
    return Decimal(str(int(h[:4], 16) % 100))