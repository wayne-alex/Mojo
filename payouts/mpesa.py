"""
M-Pesa Daraja B2C client.

Set these env vars in production:
  MPESA_CONSUMER_KEY
  MPESA_CONSUMER_SECRET
  MPESA_SHORTCODE           (B2C shortcode, e.g. 600000)
  MPESA_INITIATOR_NAME
  MPESA_SECURITY_CREDENTIAL (encrypted initiator password)
  MPESA_ENV                 "sandbox" | "production"
  MPESA_CALLBACK_URL        (public HTTPS URL to /api/payouts/mpesa/callback/)

Until keys are set, `simulate=True` short-circuits the HTTP call and marks
the withdrawal as immediately paid — useful for local flow testing.
"""
import os
import base64
import logging
import requests

logger = logging.getLogger(__name__)


class MpesaConfigError(Exception):
    pass


def _credentials():
    return {
        "consumer_key": os.getenv("MPESA_CONSUMER_KEY", ""),
        "consumer_secret": os.getenv("MPESA_CONSUMER_SECRET", ""),
        "shortcode": os.getenv("MPESA_SHORTCODE", ""),
        "initiator": os.getenv("MPESA_INITIATOR_NAME", ""),
        "security_credential": os.getenv("MPESA_SECURITY_CREDENTIAL", ""),
        "env": os.getenv("MPESA_ENV", "sandbox"),
        "callback_url": os.getenv("MPESA_CALLBACK_URL", ""),
    }


def is_configured():
    c = _credentials()
    return bool(c["consumer_key"] and c["consumer_secret"] and c["shortcode"])


def _base_url(env):
    return (
        "https://api.safaricom.co.ke"
        if env == "production"
        else "https://sandbox.safaricom.co.ke"
    )


def _access_token(creds):
    url = f"{_base_url(creds['env'])}/oauth/v1/generate?grant_type=client_credentials"
    basic = base64.b64encode(
        f"{creds['consumer_key']}:{creds['consumer_secret']}".encode()
    ).decode()
    r = requests.get(url, headers={"Authorization": f"Basic {basic}"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def initiate_b2c(*, phone, amount, remarks, reference):
    """
    Kick off an M-Pesa B2C payout.
    Returns dict: {"conversation_id": ..., "originator_conversation_id": ...}
    Raises MpesaConfigError if keys aren't set.
    """
    creds = _credentials()
    if not is_configured():
        raise MpesaConfigError(
            "M-Pesa B2C not configured. Set MPESA_* env vars or use simulate=True."
        )

    token = _access_token(creds)
    url = f"{_base_url(creds['env'])}/mpesa/b2c/v1/paymentrequest"

    body = {
        "InitiatorName": creds["initiator"],
        "SecurityCredential": creds["security_credential"],
        "CommandID": "BusinessPayment",
        "Amount": int(amount),                      # B2C wants integer KES
        "PartyA": creds["shortcode"],
        "PartyB": phone,
        "Remarks": remarks[:100],
        "QueueTimeOutURL": creds["callback_url"] + "?kind=timeout",
        "ResultURL": creds["callback_url"] + "?kind=result",
        "Occasion": reference[:100],
    }
    r = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    logger.info("mpesa b2c initiated: %s", data)
    return {
        "conversation_id": data.get("ConversationID", ""),
        "originator_conversation_id": data.get("OriginatorConversationID", ""),
    }