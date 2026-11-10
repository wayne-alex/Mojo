from django.db.models.signals import post_save
from django.dispatch import receiver

from ledger.services import (
    get_client_wallet, get_worker_earnings_wallet, get_worker_pass_wallet,
    get_or_create_wallet,
)
from ledger.models import Wallet
from .models import User, WorkerProfile, ClientProfile


@receiver(post_save, sender=User)
def create_profiles_and_wallets(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.role == User.Role.WORKER:
        WorkerProfile.objects.get_or_create(user=instance)
        get_worker_earnings_wallet(instance)
        get_worker_pass_wallet(instance)

    elif instance.role == User.Role.CLIENT:
        ClientProfile.objects.get_or_create(user=instance)
        get_client_wallet(instance)

    elif instance.role == User.Role.ADMIN:
        get_or_create_wallet(instance, Wallet.Type.PLATFORM)