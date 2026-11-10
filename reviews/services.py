from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.core.exceptions import ValidationError

from accounts.models import WorkerProfile, ClientProfile
from jobs.models import Job
from .models import Rating


@transaction.atomic
def submit_rating(job_id, author, *, score, comment=""):
    """
    Called by either party after job completion.
    Rejects if: job not completed, author not a party, already rated.
    """
    if not 1 <= int(score) <= 5:
        raise ValidationError("Score must be 1-5")

    job = Job.objects.select_for_update().get(pk=job_id)
    if job.status != Job.Status.COMPLETED:
        raise ValidationError("Job must be completed before rating")
    if author.id not in (job.client_id, job.accepted_bid.worker_id):
        raise ValidationError("You were not a party to this job")

    if author.id == job.client_id:
        subject = job.accepted_bid.worker
        direction = Rating.Direction.CLIENT_TO_WORKER
    else:
        subject = job.client
        direction = Rating.Direction.WORKER_TO_CLIENT

    if Rating.objects.filter(job=job, author=author).exists():
        raise ValidationError("You already rated this job")

    rating = Rating.objects.create(
        job=job, author=author, subject=subject,
        direction=direction, score=int(score), comment=comment,
    )

    if direction == Rating.Direction.CLIENT_TO_WORKER:
        recompute_worker_stats(subject)
    else:
        recompute_client_stats(subject)

    try:
        notify(subject, kind=Notification.Kind.RATING_RECEIVED,
               title=f"New {score}/5 rating",
               body=comment or "No comment.",
               link=f"/jobs/{job.id}", reference=str(job.id))
    except Exception:
        pass

    return rating

    return rating


@transaction.atomic
def recompute_worker_stats(worker):
    """Recompute avg_rating + completion_rate from authoritative sources."""
    wp = WorkerProfile.objects.select_for_update().get(user=worker)

    # avg_rating from CLIENT_TO_WORKER ratings
    avg = Rating.objects.filter(
        subject=worker, direction=Rating.Direction.CLIENT_TO_WORKER,
    ).aggregate(avg=Avg("score"))["avg"]
    wp.avg_rating = Decimal(str(avg)).quantize(Decimal("0.01")) if avg else Decimal("0.00")

    # completion_rate: completed jobs / (completed + cancelled-with-worker-caused)
    # For v1 we approximate as completed / (completed + rejected_bids)
    completed = wp.completed_jobs
    total = wp.total_jobs_started or completed
    if total:
        wp.completion_rate = (
            Decimal(completed) / Decimal(total) * Decimal("100")
        ).quantize(Decimal("0.01"))

    wp.save(update_fields=["avg_rating", "completion_rate"])
    return wp


@transaction.atomic
def recompute_client_stats(client):
    """Update ClientProfile.avg_rating_given from WORKER_TO_CLIENT ratings."""
    cp = ClientProfile.objects.select_for_update().get(user=client)
    avg = Rating.objects.filter(
        subject=client, direction=Rating.Direction.WORKER_TO_CLIENT,
    ).aggregate(avg=Avg("score"))["avg"]
    cp.avg_rating_given = (
        Decimal(str(avg)).quantize(Decimal("0.01")) if avg else Decimal("0.00")
    )
    cp.save(update_fields=["avg_rating_given"])
    return cp


def past_client_score_for(worker, client):
    """
    Real 'past_client' score: how THIS client rated THIS worker last time.
    Falls back to worker global avg_rating / 5 if no shared history.
    Returns a float in [0, 1].
    """
    last = (
        Rating.objects.filter(
            subject=worker,
            direction=Rating.Direction.CLIENT_TO_WORKER,
            author=client,
        )
        .order_by("-created_at")
        .first()
    )
    if last:
        return float(last.score) / 5.0

    wprofile = getattr(worker, "worker_profile", None)
    if wprofile:
        return float(wprofile.avg_rating or 0) / 5.0
    return 0.0