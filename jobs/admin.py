from django.contrib import admin
from .models import Job, Bid


class BidInline(admin.TabularInline):
    model = Bid
    extra = 0
    fields = ("worker", "price", "delivery_days", "score_total",
              "score_breakdown", "status", "pass_reference", "created_at")
    readonly_fields = ("score_total", "score_breakdown", "created_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "status", "budget_min", "budget_max",
                    "min_level", "pass_cost", "bid_count", "created_at")
    list_filter = ("status", "min_level")
    search_fields = ("title", "client__username")
    readonly_fields = ("id", "bid_count", "agreed_price", "accepted_bid",
                       "delivered_at", "auto_approve_at", "completed_at",
                       "cancelled_at", "created_at", "updated_at")
    inlines = [BidInline]


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "worker", "price", "delivery_days",
                    "score_total", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("job__title", "worker__username")
    readonly_fields = ("score_total", "score_breakdown", "created_at")