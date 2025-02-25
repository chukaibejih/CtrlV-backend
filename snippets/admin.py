from django.contrib import admin
from django.utils.timezone import now
from .models import Snippet, SnippetMetrics, SnippetView

@admin.register(Snippet)
class SnippetAdmin(admin.ModelAdmin):
    list_display = ("id", "language", "created_at", "expires_at", "view_count", "is_encrypted", "one_time_view", "is_expired")
    list_filter = ("language", "is_encrypted", "one_time_view", "expires_at")
    search_fields = ("content", "access_token")
    readonly_fields = ("id", "created_at", "view_count", "access_token", "is_expired")
    ordering = ("-created_at",)
    actions = ["reset_view_count", "expire_snippets_now"]

    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = "Expired?"

    @admin.action(description="Reset view count for selected snippets")
    def reset_view_count(self, request, queryset):
        queryset.update(view_count=0)
        self.message_user(request, "View counts have been reset.")

    @admin.action(description="Expire selected snippets immediately")
    def expire_snippets_now(self, request, queryset):
        queryset.update(expires_at=now())
        self.message_user(request, "Selected snippets have been marked as expired.")

@admin.register(SnippetView)
class SnippetViewAdmin(admin.ModelAdmin):
    list_display = ("id", "snippet", "viewed_at", "ip_hash", "user_agent")
    list_filter = ("viewed_at",)
    search_fields = ("snippet__access_token", "ip_hash", "user_agent")
    readonly_fields = ("id", "snippet", "viewed_at", "ip_hash", "user_agent")
    ordering = ("-viewed_at",)


@admin.register(SnippetMetrics)
class SnippetMetricsAdmin(admin.ModelAdmin):
    list_display = ("date", "total_snippets", "total_views")
    list_filter = ("date",)
    ordering = ("-date",)
