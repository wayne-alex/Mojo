"""
WhatsApp bot adapter. Sends OTPs and transactional messages through
whatever bot is sitting behind WHATSAPP_URL.

Env vars:
  WHATSAPP_URL     — HTTP endpoint on your bot that accepts a POST
  WHATSAPP_TOKEN   — optional bearer token your bot expects

If WHATSAPP_URL is unset, `send_whatsapp()` logs the payload and returns
success — so local dev works without a live bot.
"""
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    pass


def is_configured():
    return bool(getattr(settings, "WHATSAPP_URL", ""))


def send_whatsapp(phone, body, *, template=None, meta=None):
    """
    Send a WhatsApp message via the bot.

    phone    : E.164 format, e.g. "+254708374149"
    body     : message text (what the user sees)
    template : optional template name your bot understands
    meta     : optional dict passed through (e.g. {"purpose": "otp"})

    Returns: True on 2xx, False on failure. Raises WhatsAppError only
    on hard transport errors so callers can catch it explicitly.
    """
    if not is_configured():
        logger.warning(
            "WHATSAPP_UNCONFIGURED → to=%s template=%s meta=%s body=%r",
            phone, template, meta or {}, body,
        )
        return True

    url = settings.WHATSAPP_URL
    headers = {"Content-Type": "application/json"}
    token = getattr(settings, "WHATSAPP_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "to": phone,
        "text": body,
        "template": template,
        "meta": meta or {},
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
    except requests.RequestException as exc:
        logger.exception("whatsapp transport error: %s", exc)
        raise WhatsAppError(str(exc)) from exc

    if not (200 <= r.status_code < 300):
        logger.error("whatsapp send failed: %s %s", r.status_code, r.text[:200])
        return False

    return True