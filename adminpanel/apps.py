from django.apps import AppConfig
from django.db.models.signals import post_save, post_delete


def _invalidate(sender, instance, **kwargs):
    from django.core.cache import cache
    cache.delete(f"mojo:setting:{instance.key}")


class AdminpanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adminpanel"

    def ready(self):
        from .models import Setting
        post_save.connect(_invalidate, sender=Setting)
        post_delete.connect(_invalidate, sender=Setting)