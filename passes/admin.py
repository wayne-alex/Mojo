from django.contrib import admin
from .models import PassTier


@admin.register(PassTier)
class PassTierAdmin(admin.ModelAdmin):
    list_display = ("name", "min_budget", "max_budget", "pass_cost")
    list_editable = ("pass_cost",)
    ordering = ("min_budget",)