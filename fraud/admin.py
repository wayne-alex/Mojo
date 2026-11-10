from django.contrib import admin
from .models import DeviceFingerprint, FraudFlag, RateLimitHit


@admin.register(DeviceFingerprint)
class DeviceFingerprintAdmin(admin.ModelAdmin):
    list_display = ("user", "ip", "user_agent_hash", "created_at")
    list_filter = ("ip",)
    search_fields = ("user__username", "ip", "user_agent_hash")
    readonly_fields = [f.name for f in DeviceFingerprint._meta.fields]


@admin.register(FraudFlag)
class FraudFlagAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "reason", "created_by")
    list_filter = ("reason",)
    search_fields = ("user__username", "note")
    readonly_fields = ("id", "created_at")


@admin.register(RateLimitHit)
class RateLimitHitAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "identity", "window_start", "count")
    list_filter = ("endpoint",)
    search_fields = ("identity",)