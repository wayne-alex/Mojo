from django.contrib import admin
from .models import Rating


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("created_at", "direction", "job", "author", "subject", "score")
    list_filter = ("direction", "score")
    search_fields = ("author__username", "subject__username", "job__title")
    readonly_fields = [f.name for f in Rating._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False