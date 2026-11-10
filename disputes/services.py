from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings

from ledger.models import EscrowHold
from ledger.services import (
    release_escrow_to_worker, refund_escrow_to_client, split_escrow,
    get_worker_earnings_wallet,
)
from jobs.models import Job
from notifications.models import Notification
from notifications.services import notify
from .models import Dispute, Evidence


@transaction.atomic
def open_dispute(job_id, opener, *, reason, evidence_text="", evidence_file_url=""):
    job = Job.objects.select_for_update().get(pk=job_id)

    if job.status not in (Job.Status.IN_PROGRESS, Job.Status.DELIVERED):
        raise ValidationError("Can only dispute an in-progress or delivered job")

    if opener.id not in (job.client_id, job.accepted_bid.worker_id):
        raise ValidationError("You are not a party to this job")

    if Dispute.objects.filter(job=job).exists():
        raise ValidationError("Dispute already exists for this job")

    hold = EscrowHold.objects.filter(
        reference=f"job:{job.id}", status=EscrowHold.Status.HELD,
    ).first()
    if not hold:
        raise ValidationError("No escrow held — cannot dispute")

    d = Dispute.objects.create(job=job, opened_by=opener, reason=reason)
    if evidence_text or evidence_file_url:
        Evidence.objects.create(
            dispute=d, submitted_by=opener,
            text=evidence_text, file_url=evidence_file_url,
        )

    job.status = Job.Status.DISPUTED
    job.save(update_fields=["status"])
    other = job.client if opener.id == job.accepted_bid.worker_id else job.accepted_bid.worker
    try:
        notify(other, kind=Notification.Kind.DISPUTE_OPENED,
               title="A dispute was opened",
               body=f"{job.title}: {reason}",
               link=f"/disputes/{d.id}", reference=str(d.id))
    except Exception:
        pass
    return d


@transaction.atomic
def submit_evidence(dispute_id, submitter, *, text="", file_url=""):
    d = Dispute.objects.select_for_update().get(pk=dispute_id)
    if d.status not in (Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW):
        raise ValidationError("Dispute is already resolved")
    if submitter.id not in (d.job.client_id, d.job.accepted_bid.worker_id):
        raise ValidationError("Not a party to this dispute")
    if not (text or file_url):
        raise ValidationError("Evidence must have text or a file")
    return Evidence.objects.create(
        dispute=d, submitted_by=submitter, text=text, file_url=file_url,
    )


@transaction.atomic
def resolve(dispute_id, admin, *, outcome, note="", client_share=None, worker_share=None):
    """
    outcome: "pay_worker" | "refund_client" | "split"
    For split, client_share + worker_share must equal escrow amount; platform fee is 0
    (or you can deduct fee from worker_share before splitting — v1: no fee on splits).
    """
    d = Dispute.objects.select_for_update().get(pk=dispute_id)
    if d.status not in (Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW):
        raise ValidationError("Dispute already resolved")
    if admin.role != "admin":
        raise ValidationError("Only admins can resolve disputes")

    job = d.job
    worker = job.accepted_bid.worker
    hold = EscrowHold.objects.select_for_update().get(
        reference=f"job:{job.id}", status=EscrowHold.Status.HELD,
    )
    escrow_amount = hold.amount
    ref = f"dispute:{d.id}"

    if outcome == "pay_worker":
        fee_pct = Decimal(settings.MOJO_PLATFORM_FEE_PCT)
        platform_fee = (escrow_amount * fee_pct).quantize(Decimal("0.01"))
        release_escrow_to_worker(
            hold_id=hold.id,
            worker_wallet_id=get_worker_earnings_wallet(worker).id,
            platform_fee=platform_fee,
            reference=ref,
            meta={"dispute_id": str(d.id), "outcome": "pay_worker"},
        )
        d.status = Dispute.Status.RESOLVED_PAY_WORKER
        d.worker_payout = escrow_amount - platform_fee
        d.client_refund = Decimal("0.00")

    elif outcome == "refund_client":
        refund_escrow_to_client(
            hold_id=hold.id, reference=ref,
            meta={"dispute_id": str(d.id), "outcome": "refund_client"},
        )
        d.status = Dispute.Status.RESOLVED_REFUND_CLIENT
        d.client_refund = escrow_amount
        d.worker_payout = Decimal("0.00")

    elif outcome == "split":
        cs = Decimal(client_share or "0")
        ws = Decimal(worker_share or "0")
        if cs + ws != escrow_amount:
            raise ValidationError(
                f"Split must sum to {escrow_amount} (got {cs + ws})"
            )
        split_escrow(
            hold_id=hold.id,
            client_share=cs,
            worker_wallet_id=get_worker_earnings_wallet(worker).id,
            worker_share=ws,
            platform_fee=Decimal("0"),
            reference=ref,
            meta={"dispute_id": str(d.id), "outcome": "split"},
        )
        d.status = Dispute.Status.RESOLVED_SPLIT
        d.client_refund = cs
        d.worker_payout = ws

    else:
        raise ValidationError(f"Unknown outcome: {outcome}")

    d.resolution_note = note
    d.resolved_by = admin
    d.resolved_at = timezone.now()
    d.save()

    # Mark job as completed regardless of payout direction
    job.status = Job.Status.COMPLETED
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "completed_at"])
    try:
        notify(job.client, kind=Notification.Kind.DISPUTE_RESOLVED,
               title="Dispute resolved",
               body=f"Outcome: {outcome}. Note: {note or '(none)'}",
               link=f"/disputes/{d.id}", reference=str(d.id))
        notify(job.accepted_bid.worker, kind=Notification.Kind.DISPUTE_RESOLVED,
               title="Dispute resolved",
               body=f"Outcome: {outcome}. Note: {note or '(none)'}",
               link=f"/disputes/{d.id}", reference=str(d.id))
    except Exception:
        pass

    return d