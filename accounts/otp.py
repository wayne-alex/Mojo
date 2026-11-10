import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from notifications.whatsapp import send_whatsapp, WhatsAppError
from .models import OTPCode


OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def _hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_code():
    # 6 digits, zero-padded
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


@transaction.atomic
def issue_otp(user, purpose, *, phone=None):
    phone = phone or user.phone
    if not phone:
        raise ValidationError("No phone number on file")

    OTPCode.objects.filter(
        user=user, purpose=purpose, consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    code = _generate_code()
    otp = OTPCode.objects.create(
        user=user,
        phone=phone,
        purpose=purpose,
        code_hash=_hash(code),
        code=code,                       # ← store plaintext for admin lookup
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )

    body = (
        f"Your Mojo verification code is {code}.\n"
        f"Valid for {OTP_TTL_MINUTES} minutes. "
        f"Do not share this code with anyone."
    )
    try:
        send_whatsapp(phone, body, template="otp", meta={
            "purpose": purpose, "otp_id": str(otp.id),
        })
    except WhatsAppError:
        pass

    return otp

@transaction.atomic
def verify_otp(user, purpose, code):
    """
    Consume a valid OTP. Returns True on success. Raises ValidationError
    with a clear message on any failure (expired, wrong, too many attempts,
    already consumed).
    """
    if not code:
        raise ValidationError("Enter the 6-digit code")

    otp = (
        OTPCode.objects
        .select_for_update()
        .filter(user=user, purpose=purpose, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if not otp:
        raise ValidationError("No active code. Request a new one.")

    if otp.expires_at <= timezone.now():
        otp.consumed_at = timezone.now()
        otp.save(update_fields=["consumed_at"])
        raise ValidationError("Code expired. Request a new one.")

    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise ValidationError("Too many attempts. Request a new code.")

    if _hash(code.strip()) != otp.code_hash:
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        remaining = OTP_MAX_ATTEMPTS - otp.attempts
        raise ValidationError(
            f"Incorrect code. {remaining} attempt(s) left."
        )

    otp.consumed_at = timezone.now()
    otp.save(update_fields=["consumed_at"])
    return True