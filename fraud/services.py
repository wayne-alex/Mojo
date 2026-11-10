import hashlib
import re
from datetime import timedelta, timezone as dt_timezone
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from accounts.models import WorkerProfile
from .models import RateLimitHit, DeviceFingerprint, FraudFlag

User = get_user_model()


# ------------------------------------------------------------------ #
# Rate limiting                                                       #
# ------------------------------------------------------------------ #

DEFAULT_WINDOWS = {
    "register":  (timedelta(hours=1), 5),     # 5 signups / hour / IP
    "bid":       (timedelta(minutes=1), 10),  # 10 bids / minute / user
    "withdraw":  (timedelta(hours=24), 3),    # 3 withdrawals / day / user
    "otp_resend": (timedelta(minutes=2), 2),  # 2 resends / 2 min

}


def check_rate_limit(endpoint, identity):
    """
    Return (allowed: bool, retry_after_seconds: int).
    On allowed, increments the counter for the current window.
    """
    window, max_hits = DEFAULT_WINDOWS[endpoint]
    now = timezone.now()

    # Align to window buckets
    epoch = int(now.timestamp())
    window_secs = int(window.total_seconds())
    window_start = timezone.datetime.fromtimestamp(
        (epoch // window_secs) * window_secs, tz=dt_timezone.utc,
    )

    with transaction.atomic():
        hit, _ = RateLimitHit.objects.select_for_update().get_or_create(
            endpoint=endpoint, identity=str(identity), window_start=window_start,
            defaults={"count": 0},
        )
        if hit.count >= max_hits:
            retry_after = window_secs - (epoch % window_secs)
            return False, retry_after
        hit.count += 1
        hit.save(update_fields=["count"])
    return True, 0


# ------------------------------------------------------------------ #
# Device / IP tracking                                                #
# ------------------------------------------------------------------ #

def _hash_user_agent(ua):
    return hashlib.sha256((ua or "").encode()).hexdigest()[:32]


def record_device(user, request):
    if request is None:
        return None
    ip = _client_ip(request)
    ua_hash = _hash_user_agent(request.META.get("HTTP_USER_AGENT", ""))
    return DeviceFingerprint.objects.create(
        user=user, ip=ip, user_agent_hash=ua_hash,
    )


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def find_accounts_sharing_ip(ip):
    if not ip:
        return User.objects.none()
    user_ids = (
        DeviceFingerprint.objects.filter(ip=ip)
        .values_list("user_id", flat=True).distinct()
    )
    return User.objects.filter(id__in=user_ids)


def find_accounts_sharing_device(ua_hash):
    if not ua_hash:
        return User.objects.none()
    user_ids = (
        DeviceFingerprint.objects.filter(user_agent_hash=ua_hash)
        .values_list("user_id", flat=True).distinct()
    )
    return User.objects.filter(id__in=user_ids)


def flag_user(user, *, reason, note="", created_by=None):
    """Set fraud_flag on profile + write audit row. Idempotent per reason."""
    flag = FraudFlag.objects.create(
        user=user, reason=reason, note=note, created_by=created_by,
    )
    if user.role == "worker":
        WorkerProfile.objects.filter(user=user).update(fraud_flag=True)
    return flag


# ------------------------------------------------------------------ #
# Content checks                                                      #
# ------------------------------------------------------------------ #

PHONE_RE = re.compile(
    r"(?:(?:\+|0{0,2})?\d[\d\s\-().]{6,}\d)"
)
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s]+", re.IGNORECASE,
)


def sanitize_message(text, *, allow_contact=False):
    """
    Bid messages and evidence texts are scanned before saving.
    If `allow_contact` is False, reject any phone number or URL.
    """
    if not text:
        return text
    if allow_contact:
        return text
    if PHONE_RE.search(text):
        raise ValidationError("Phone numbers are not allowed until a job is accepted")
    if URL_RE.search(text):
        raise ValidationError("Links are not allowed until a job is accepted")
    return text


# ------------------------------------------------------------------ #
# ID uniqueness (one account per national ID)                         #
# ------------------------------------------------------------------ #

def check_id_uniqueness(user, id_number):
    """
    Enforce one account per national ID. Called when KYC is submitted.
    """
    if not id_number:
        return
    clash = (
        WorkerProfile.objects
        .filter(id_number=id_number)
        .exclude(user=user)
        .exists()
    )
    if clash:
        flag_user(user, reason=FraudFlag.Reason.MULTI_ACCOUNT,
                  note=f"Duplicate ID attempt: {id_number[-4:]}****")
        raise ValidationError("This ID is already registered to another account")