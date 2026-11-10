from django.conf import settings
from decimal import Decimal


def get_bid_weights():
    """DB override wins; falls back to MOJO_BID_WEIGHTS from settings.py."""
    from adminpanel.services import get_setting
    raw = get_setting(
        "MOJO_BID_WEIGHTS",
        default=settings.MOJO_BID_WEIGHTS,
    )
    return raw


def get_new_worker_config():
    from adminpanel.services import get_setting
    return get_setting(
        "MOJO_NEW_WORKER",
        default=settings.MOJO_NEW_WORKER,
    )


def get_platform_fee_pct():
    from adminpanel.services import get_setting
    val = get_setting(
        "MOJO_PLATFORM_FEE_PCT",
        default=settings.MOJO_PLATFORM_FEE_PCT,
    )
    return Decimal(str(val))


def get_pending_hold_hours():
    from adminpanel.services import get_setting
    return int(get_setting(
        "MOJO_PENDING_HOLD_HOURS",
        default=settings.MOJO_PENDING_HOLD_HOURS,
    ))


def get_auto_approve_days():
    from adminpanel.services import get_setting
    return int(get_setting(
        "MOJO_AUTO_APPROVE_DAYS",
        default=settings.MOJO_AUTO_APPROVE_DAYS,
    ))


def get_max_revisions():
    from adminpanel.services import get_setting
    return int(get_setting(
        "MOJO_MAX_REVISIONS",
        default=settings.MOJO_MAX_REVISIONS,
    ))