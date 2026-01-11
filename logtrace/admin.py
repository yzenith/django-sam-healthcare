# logtrace/admin.py
from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone

from .models import TraceLog, TraceStep


@admin.action(description="Delete TraceLogs older than 30 days (and their steps)")
def purge_tracelogs_older_than_30_days(modeladmin, request, queryset):
    cutoff = timezone.now() - timedelta(days=30)
    old_qs = queryset.filter(created_at__lt=cutoff)

    count = old_qs.count()
    old_qs.delete()  # cascades to TraceStep due to FK on_delete=models.CASCADE

    modeladmin.message_user(
        request,
        f"Deleted {count} TraceLogs older than 30 days (and their steps).",
        level=messages.SUCCESS,
    )


class TraceStepInline(admin.TabularInline):
    model = TraceStep
    extra = 0
    fields = ("sequence", "step_name", "status", "message", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("sequence",)


@admin.register(TraceLog)
class TraceLogAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = (
        "created_at",
        "trace_id",
        "input_type",
        "status",
        "error_count",
        "duration_ms",
        "source_system",
        "message_type",
        "review_required",
        "business_impact",
    )
    list_filter = ("status", "input_type", "created_at")
    search_fields = ("trace_id", "summary", "raw_payload")
    readonly_fields = ("created_at",)
    inlines = [TraceStepInline]
    actions = [purge_tracelogs_older_than_30_days]

    # Optional: keep admin list fast if it grows large
    list_per_page = 50


@admin.register(TraceStep)
class TraceStepAdmin(admin.ModelAdmin):
    list_display = ("created_at", "trace_log", "sequence", "step_name", "status")
    list_filter = ("status", "step_name", "created_at")
    search_fields = ("trace_log__trace_id", "message")
    readonly_fields = ("created_at",)
