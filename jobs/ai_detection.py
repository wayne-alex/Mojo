"""
AI detection service. Swappable between providers.

Supported providers (set AI_DETECTION_PROVIDER in env):
  - "gptzero"      → https://gptzero.me/api
  - "winston"      → https://api.gowinston.ai/v2/ai-content-detection
  - "fake"         → deterministic hash (dev only)

Set AI_DETECTION_API_KEY in env for real providers.
"""
import hashlib
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AIDetectionError(Exception):
    pass


def _call_gptzero(text: str, api_key: str) -> float:
    """
    GPTZero API. Returns AI probability as 0–100.
    Docs: https://gptzero.stoplight.io/docs/gptzero-api
    """
    try:
        r = requests.post(
            "https://api.gptzero.me/v2/predict/text",
            json={"document": text[:20000]},  # 20k char limit
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AIDetectionError(f"GPTZero transport error: {exc}") from exc

    if r.status_code >= 400:
        raise AIDetectionError(f"GPTZero HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    try:
        # GPTZero returns documents[0].completely_generated_prob (0–1)
        prob = data["documents"][0]["completely_generated_prob"]
        return round(float(prob) * 100, 2)
    except (KeyError, IndexError, TypeError) as exc:
        raise AIDetectionError(f"GPTZero response shape unexpected: {data}") from exc


def _call_winston(text: str, api_key: str) -> float:
    """
    Winston AI API. Returns AI probability as 0–100.
    Docs: https://docs.gowinston.ai/api-reference
    """
    try:
        r = requests.post(
            "https://api.gowinston.ai/v2/ai-content-detection",
            json={"text": text[:20000], "version": "latest"},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AIDetectionError(f"Winston transport error: {exc}") from exc

    if r.status_code >= 400:
        raise AIDetectionError(f"Winston HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    try:
        # Winston returns score as 0–1 (AI probability)
        score = float(data.get("score", 0))
        return round(score * 100, 2)
    except (KeyError, TypeError) as exc:
        raise AIDetectionError(f"Winston response shape unexpected: {data}") from exc


def _call_fake(text: str) -> float:
    """Dev-only: deterministic hash so the same content always gives the same score."""
    h = hashlib.sha256(text.encode()).hexdigest()
    return round((int(h[:4], 16) % 10000) / 100, 2)  # 0.00 – 99.99


def detect_ai(text: str) -> float:
    """
    Return AI probability score (0–100). Higher = more likely AI.
    Raises AIDetectionError if the provider fails.
    """
    text = (text or "").strip()
    if len(text) < 20:
        raise AIDetectionError("Not enough text to analyze (min 20 chars)")

    provider = getattr(settings, "AI_DETECTION_PROVIDER", "fake")
    api_key = getattr(settings, "AI_DETECTION_API_KEY", "")

    if provider == "gptzero":
        if not api_key:
            raise AIDetectionError("AI_DETECTION_API_KEY not configured for gptzero")
        return _call_gptzero(text, api_key)
    if provider == "winston":
        if not api_key:
            raise AIDetectionError("AI_DETECTION_API_KEY not configured for winston")
        return _call_winston(text, api_key)

    # Default: fake (dev mode)
    return _call_fake(text)