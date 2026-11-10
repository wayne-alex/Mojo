from django.contrib import admin
from .models import Setting


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "value_type", "updated_at")
    list_editable = ("value", "value_type")
    search_fields = ("key", "description")
    ordering = ("key",)