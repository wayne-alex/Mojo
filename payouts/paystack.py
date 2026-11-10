import hmac
import hashlib
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"


class PaystackError(Exception):
    pass


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_transaction(*, email, phone, amount_kes, reference, metadata=None, callback_url=""):
    """
    Returns {"authorization_url": "...", "access_code": "...", "reference": "..."}
    Client redirects to authorization_url to complete payment.
    """
    amount_cents = int(float(amount_kes) * 100)
    payload = {
        "email": email or "user@mojo.local",
        "amount": amount_cents,
        "currency": "KES",
        "reference": reference,
        "channels": ["mobile_money"],
        "metadata": metadata or {},
    }
    if phone:
        payload["phone"] = phone
    if callback_url:
        payload["callback_url"] = callback_url

    r = requests.post(
        f"{PAYSTACK_BASE}/transaction/initialize",
        json=payload,
        headers=_headers(),
        timeout=20,
    )
    data = r.json()
    if not data.get("status"):
        raise PaystackError(data.get("message", "Initialize failed"))
    return data["data"]


def verify_transaction(reference):
    """
    Confirm a transaction with Paystack before crediting anything.
    Returns the transaction data dict (with status, amount, currency).
    Raises PaystackError on transport failure or non-success.
    """
    try:
        r = requests.get(
            f"{PAYSTACK_BASE}/transaction/verify/{reference}",
            headers=_headers(),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PaystackError(str(exc)) from exc

    data = r.json() if r.content else {}
    if not data.get("status"):
        raise PaystackError(data.get("message", "Verify failed"))

    txn = data["data"]
    if txn.get("status") != "success":
        raise PaystackError(f"Transaction status: {txn.get('status')}")
    if txn.get("currency") != "KES":
        raise PaystackError(f"Unexpected currency: {txn.get('currency')}")
    return txn


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Constant-time HMAC SHA-512 check against the raw request body."""
    if not signature:
        return False
    secret = settings.PAYSTACK_SECRET_KEY.encode("utf-8")
    expected = hmac.new(secret, msg=raw_body, digestmod=hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)