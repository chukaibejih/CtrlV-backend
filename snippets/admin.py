from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from .models import Snippet, SnippetMetrics, SnippetView, VSCodeExtensionMetrics, VSCodeTelemetryEvent

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


@admin.register(VSCodeTelemetryEvent)
class VSCodeTelemetryEventAdmin(admin.ModelAdmin):
    list_display = ('event_name', 'client_id', 'timestamp', 'language', 'code_length', 'vs_code_version', 'has_error')
    list_filter = ('event_name', 'vs_code_version', 'timestamp', 'language')
    search_fields = ('client_id', 'error_message')
    date_hierarchy = 'timestamp'
    readonly_fields = ('id', 'event_type', 'event_name', 'client_id', 'timestamp', 
                      'vs_code_version', 'language', 'code_length', 'error_message', 
                      'request_data_pretty')
    
    def has_error(self, obj):
        return bool(obj.error_message)
    has_error.boolean = True
    has_error.short_description = 'Error'
    
    def request_data_pretty(self, obj):
        """Pretty print JSON data"""
        if not obj.request_data:
            return None
            
        try:
            import json
            formatted_json = json.dumps(obj.request_data, indent=2)
            return mark_safe(f'<pre>{formatted_json}</pre>')
        except Exception:
            return str(obj.request_data)
    request_data_pretty.short_description = 'Request Data'
    


@admin.register(VSCodeExtensionMetrics)
class VSCodeExtensionMetricsAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_actions', 'selection_shares', 'file_shares', 
                   'unique_clients', 'error_count', 'error_rate')
    list_filter = ('date',)
    date_hierarchy = 'date'
    readonly_fields = ('date', 'total_actions', 'selection_shares', 'file_shares',
                      'unique_clients', 'error_count', 'error_rate', 'detail_link')
    
    def error_rate(self, obj):
        """Calculate error rate as percentage"""
        if not obj.total_actions:
            return "0%"
        rate = (obj.error_count / obj.total_actions) * 100
        return f"{rate:.2f}%"
    error_rate.short_description = 'Error Rate'
    
    def detail_link(self, obj):
        """Link to filtered telemetry events for this date"""
        if not obj:
            return ""
            
        url = reverse('admin:snippets_vscodetelemetryevent_changelist')
        link = f'<a href="{url}?timestamp__date={obj.date}">View detailed events</a>'
        return mark_safe(link)
    detail_link.short_description = 'Details'



# Update the existing SnippetMetrics Admin
@admin.register(SnippetMetrics)
class SnippetMetricsAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_snippets', 'total_views', 'views_per_snippet')
    list_filter = ('date',)
    date_hierarchy = 'date'
    
    def views_per_snippet(self, obj):
        if not obj.total_snippets:
            return 0
        return f"{obj.total_views / obj.total_snippets:.2f}"
    views_per_snippet.short_description = 'Views Per Snippet'