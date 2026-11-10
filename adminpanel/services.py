import json
from decimal import Decimal
from django.core.cache import cache

from .models import Setting

_CACHE_PREFIX = "mojo:setting:"
_CACHE_TTL = 60  # seconds


def _coerce(raw, value_type):
    if value_type == Setting.ValueType.INT:
        return int(raw)
    if value_type == Setting.ValueType.DECIMAL:
        return Decimal(str(raw))
    if value_type == Setting.ValueType.BOOL:
        return str(raw).lower() in ("1", "true", "yes", "on")
    if value_type == Setting.ValueType.JSON:
        return json.loads(raw)
    return raw


def get_setting(key, default=None):
    """
    Cached fetch. DB row wins; otherwise default (usually from settings.py).
    Cache invalidated in Setting.save()/delete().
    """
    cache_key = _CACHE_PREFIX + key
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        row = Setting.objects.get(key=key)
    except Setting.DoesNotExist:
        return default

    try:
        value = _coerce(row.value, row.value_type)
    except Exception:
        return default

    cache.set(cache_key, value, _CACHE_TTL)
    return value


def set_setting(key, value, *, value_type=Setting.ValueType.STRING, description=""):
    if value_type == Setting.ValueType.JSON:
        serialized = json.dumps(value)
    elif isinstance(value, bool):
        serialized = "true" if value else "false"
    else:
        serialized = str(value)

    row, _ = Setting.objects.update_or_create(
        key=key,
        defaults={
            "value": serialized,
            "value_type": value_type,
            "description": description,
        },
    )
    cache.delete(_CACHE_PREFIX + key)
    return row


def invalidate_cache(key):
    cache.delete(_CACHE_PREFIX + key)