from django.contrib import admin
from .models import Withdrawal


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "status", "mpesa_number",
                    "mpesa_receipt", "requested_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("user__username", "mpesa_number", "reference", "mpesa_receipt")
    readonly_fields = [f.name for f in Withdrawal._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False