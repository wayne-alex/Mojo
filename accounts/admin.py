from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, WorkerProfile, ClientProfile, Skill, OTPCode


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "phone", "role", "is_verified", "is_active", "date_joined")
    list_filter = ("role", "is_verified", "is_active")
    search_fields = ("username", "phone", "email")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Mojo", {"fields": ("role", "phone", "is_verified")}),
    )


@admin.register(WorkerProfile)
class WorkerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "level", "accuracy_score", "avg_rating",
                    "completion_rate", "completed_jobs", "fraud_flag")
    list_filter = ("level", "fraud_flag")
    search_fields = ("user__username", "user__phone", "full_name")
    filter_horizontal = ("skills",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business_name", "is_verified",
                    "auto_approved", "jobs_posted")
    list_filter = ("is_verified", "auto_approved")
    search_fields = ("user__username", "user__phone", "business_name")


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "phone", "code", "expires_at", "consumed_at", "attempts")
    list_filter = ("purpose", "consumed_at")
    search_fields = ("user__username", "user__phone", "phone", "code")
    readonly_fields = ("id", "user", "phone", "purpose", "code", "code_hash",
                       "expires_at", "consumed_at", "attempts", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request): return False

    def has_change_permission(self, request, obj=None): return False
