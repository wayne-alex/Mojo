from django.db import transaction
from .models import Notification


@transaction.atomic
def notify(user, *, kind, title, body="", link="", reference=""):
    """
    Persist an in-app notification. Failures must never break the caller
    (wrapped in the caller's try/except, but also safe on its own).
    """
    return Notification.objects.create(
        user=user, kind=kind, title=title, body=body,
        link=link, reference=reference,
    )


def mark_read(user, notification_id):
    return Notification.objects.filter(user=user, id=notification_id).update(read=True)


def mark_all_read(user):
    return Notification.objects.filter(user=user, read=False).update(read=True)