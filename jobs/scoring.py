from decimal import Decimal
from config.settings_helpers import get_bid_weights, get_new_worker_config
from jobs.models import Bid


def score_bid(bid, job):
    """Returns (total_score, breakdown). Weights come from admin settings."""
    weights = get_bid_weights()
    nw = get_new_worker_config()

    worker = bid.worker
    wprofile = getattr(worker, "worker_profile", None)

    # --- Price fit (default 30) ---
    if job.budget_max == job.budget_min:
        price_fit = float(weights["price_fit"])
    elif bid.price > job.budget_max:
        price_fit = 0.0
    else:
        span = job.budget_max - job.budget_min
        pos = float((bid.price - job.budget_min) / span)   # 0=min, 1=max
        pos = max(0.0, min(1.0, pos + 0.25))
        price_fit = weights["price_fit"] * pos
    price_fit = round(price_fit, 2)

    # --- Rating + accuracy (default 30) ---
    rating = float(wprofile.avg_rating or 0) / 5.0 if wprofile else 0.0
    accuracy = float(wprofile.accuracy_score or 0) / 100.0 if wprofile else 0.0
    rating_score = round(weights["rating"] * (0.6 * rating + 0.4 * accuracy), 2)

    # --- Completion rate (default 20) ---
    completion = float(wprofile.completion_rate or 0) / 100.0 if wprofile else 0.0
    completion_score = round(weights["completion"] * completion, 2)

    # --- Skill match (default 10) ---
    required = set(job.required_skills.values_list("id", flat=True))
    have = set(wprofile.skills.values_list("id", flat=True)) if wprofile else set()
    if required:
        skill_score = round(weights["skill"] * (len(required & have) / len(required)), 2)
    else:
        skill_score = float(weights["skill"])

    # --- Past client scores (default 10) ---
    from reviews.services import past_client_score_for
    past_client_ratio = past_client_score_for(worker, job.client)
    past_client_score = round(weights["past_client"] * past_client_ratio, 2)
    # --- New-worker boost (decision #7) ---
    boost = Decimal("0")
    completed = wprofile.completed_jobs if wprofile else 0
    if completed < nw["threshold"] and not (wprofile and wprofile.fraud_flag):
        remaining = nw["threshold"] - completed
        boost = Decimal(str(nw["max_boost"])) * Decimal(remaining) / Decimal(nw["threshold"])

    total = Decimal(str(
        price_fit + rating_score + completion_score + skill_score + past_client_score
    )) + boost

    breakdown = {
        "price_fit": price_fit,
        "rating": rating_score,
        "completion": completion_score,
        "skill": skill_score,
        "past_client": past_client_score,
        "new_worker_boost": float(boost),
    }
    return round(total, 2), breakdown


def top_bids_for_job(job):
    """Top 3 + recommended. Fraud-flagged or zero-score bids never shown."""
    qs = (
        job.bids.filter(status=Bid.Status.SUBMITTED)
        .exclude(worker__worker_profile__fraud_flag=True)
        .exclude(score_total__lt=Decimal("1"))
        .order_by("-score_total", "created_at")
    )
    top3 = list(qs[:3])
    recommended = None
    if top3:
        in_budget = [b for b in top3 if b.price <= job.budget_max]
        recommended = in_budget[0] if in_budget else top3[0]
    return top3, recommended