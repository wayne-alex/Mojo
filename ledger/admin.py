from django.contrib import admin
from .models import Wallet, Transaction, EscrowHold


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "type", "pending_balance", "available_balance", "updated_at")
    list_filter = ("type",)
    search_fields = ("owner__username", "owner__phone", "id")
    readonly_fields = ("id", "updated_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "wallet", "type", "amount", "balance_after", "status", "reference")
    list_filter = ("type", "status")
    search_fields = ("reference", "wallet__owner__username")
    readonly_fields = [f.name for f in Transaction._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(EscrowHold)
class EscrowHoldAdmin(admin.ModelAdmin):
    list_display = ("id", "reference", "amount", "status", "created_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("reference",)
    readonly_fields = ("id", "created_at", "resolved_at")