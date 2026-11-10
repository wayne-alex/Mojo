from django.contrib import admin
from .models import Dispute, Evidence


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 0
    readonly_fields = ("id", "submitted_by", "text", "file_url", "created_at")


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "opened_by", "status", "created_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("job__title", "opened_by__username", "reason")
    inlines = [EvidenceInline]
    readonly_fields = [f.name for f in Dispute._meta.fields if f.name not in
                       ("status", "resolution_note", "resolved_by")]