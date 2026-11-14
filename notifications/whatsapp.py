import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    pass


def is_configured():
    return bool(getattr(settings, "WHATSAPP_URL", ""))


def send_whatsapp(phone, body, *, template=None, meta=None):
    """
    phone : international format, e.g. "+254708374149"
    body  : message text
    Returns True on 2xx, False on failure. Raises WhatsAppError on
    transport errors or when the bot is not ready.
    """
    if not is_configured():
        if settings.DEBUG:
            logger.warning("WHATSAPP_UNCONFIGURED to=%s body=%r", phone, body)
            return True
        raise WhatsAppError("WHATSAPP_URL is not configured")

    payload = {"to": phone, "text": body}

    try:
        r = requests.post(
            settings.WHATSAPP_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.exception("whatsapp transport error: %s", exc)
        raise WhatsAppError(str(exc)) from exc

    if r.status_code == 503:
        raise WhatsAppError("bot not ready")
    if r.status_code == 404:
        logger.warning("number not on WhatsApp: %s", phone)
        return False
    if not (200 <= r.status_code < 300):
        logger.error("whatsapp send failed: %s %s", r.status_code, r.text[:200])
        return False

    return True