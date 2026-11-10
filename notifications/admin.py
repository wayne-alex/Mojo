from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "title", "read")
    list_filter = ("kind", "read")
    search_fields = ("user__username", "title", "reference")
    readonly_fields = [f.name for f in Notification._meta.fields]