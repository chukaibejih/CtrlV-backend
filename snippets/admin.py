from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from .models import Snippet, SnippetMetrics, SnippetView, SnippetDiff, VSCodeExtensionMetrics, VSCodeTelemetryEvent

class SnippetViewInline(admin.TabularInline):
    model = SnippetView
    extra = 0
    readonly_fields = ('id', 'viewed_at', 'ip_hash', 'user_agent', 'location')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False

class VersionInline(admin.TabularInline):
    model = Snippet
    fk_name = 'parent_snippet'
    extra = 0
    readonly_fields = ('id', 'version', 'content_preview', 'language', 'created_at', 'view_count', 'version_link')
    fields = ('version', 'version_link', 'language', 'created_at', 'view_count', 'content_preview')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False
        
    def version_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.id])
        return mark_safe('<a href="{}">View Version</a>'.format(url))
    version_link.short_description = 'View'
    
    def content_preview(self, obj):
        if obj.is_encrypted:
            return "[Encrypted Content]"
        preview = obj.content[:200] + "..." if len(obj.content) > 200 else obj.content
        return mark_safe('<pre>{}</pre>'.format(preview))
    content_preview.short_description = 'Content Preview'

class SnippetDiffInline(admin.TabularInline):
    model = SnippetDiff
    fk_name = 'source_snippet'
    extra = 0
    readonly_fields = ('id', 'target_snippet', 'created_at', 'diff_preview', 'target_link')
    fields = ('target_snippet', 'created_at', 'diff_preview', 'target_link')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False
        
    def diff_preview(self, obj):
        if obj.diff_content:
            preview = obj.diff_content[:100] + "..." if len(obj.diff_content) > 100 else obj.diff_content
            return mark_safe('<pre>{}</pre>'.format(preview))
        return "-"
    diff_preview.short_description = 'Diff Preview'
    
    def target_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.target_snippet.id])
        return mark_safe('<a href="{}">View Target</a>'.format(url))
    target_link.short_description = 'Target'

@admin.register(Snippet)
class SnippetAdmin(admin.ModelAdmin):
    list_display = ('id', 'language', 'created_at', 'expires_at', 'view_count', 
                    'is_encrypted', 'one_time_view', 'has_password', 'version', 'parent_link')
    list_filter = ('language', 'is_encrypted', 'one_time_view', 'created_at', 'version')
    search_fields = ('id', 'content', 'language', 'creator_ip_hash')
    readonly_fields = ('id', 'access_token', 'created_at', 'view_count', 'parent_snippet', 'version', 
                      'content_preview', 'expires_in', 'sharing_url', 'creator_ip_hash', 'creator_location')
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'language', 'content_preview', 'created_at')
        }),
        ('Content', {
            'fields': ('content',),
            'classes': ('collapse',),
        }),
        ('Security & Access', {
            'fields': ('access_token', 'is_encrypted', 'one_time_view', 'password_hash', 'password_salt')
        }),
        ('Expiration', {
            'fields': ('expires_at', 'expires_in')
        }),
        ('Analytics', {
            'fields': ('view_count', 'sharing_url', 'creator_ip_hash', 'creator_location')
        }),
        ('Versioning', {
            'fields': ('parent_snippet', 'version')
        }),
    )
    inlines = [VersionInline, SnippetDiffInline, SnippetViewInline]
    
    def has_password(self, obj):
        return bool(obj.password_hash and obj.password_salt)
    has_password.boolean = True
    has_password.short_description = 'Password Protected'
    
    def content_preview(self, obj):
        if obj.is_encrypted:
            return "[Encrypted Content]"
        preview = obj.content[:200] + "..." if len(obj.content) > 200 else obj.content
        return mark_safe('<pre>{}</pre>'.format(preview))
    content_preview.short_description = 'Content Preview'
    
    def expires_in(self, obj):
        if obj.expires_at <= now():
            return "Expired"
        delta = obj.expires_at - now()
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            return f"{days} days, {hours} hours"
        elif hours > 0:
            return f"{hours} hours, {minutes} minutes"
        else:
            return f"{minutes} minutes, {seconds} seconds"
    expires_in.short_description = 'Expires In'
    
    def sharing_url(self, obj):
        base_url = "https://ctrlv.codes"  # Replace with your actual base URL
        url = obj.get_sharing_url(base_url)
        return mark_safe('<a href="{0}" target="_blank">{0}</a>'.format(url))
    sharing_url.short_description = 'Sharing URL'
    
    def parent_link(self, obj):
        if obj.parent_snippet:
            url = reverse('admin:snippets_snippet_change', args=[obj.parent_snippet.id])
            return mark_safe('<a href="{}">View Parent</a>'.format(url))
        return "-"
    parent_link.short_description = 'Parent'
    
    def save_model(self, request, obj, form, change):
        # Handle password protection
        if 'password' in form.data and form.data['password']:
            obj.set_password(form.data['password'])
        super().save_model(request, obj, form, change)

@admin.register(SnippetView)
class SnippetViewAdmin(admin.ModelAdmin):
    list_display = ('id', 'snippet_link', 'viewed_at', 'ip_hash', 'user_agent', 'location')
    list_filter = ('viewed_at',)
    search_fields = ('ip_hash', 'user_agent', 'location')
    readonly_fields = ('id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent', 'location')
    
    def has_add_permission(self, request):
        return False
    
    def snippet_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.snippet.id])
        return mark_safe('<a href="{}">{}</a>'.format(url, obj.snippet.id))
    snippet_link.short_description = 'Snippet'

@admin.register(SnippetMetrics)
class SnippetMetricsAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_snippets', 'total_views', 'views_per_snippet')
    list_filter = ('date',)
    readonly_fields = ('date', 'total_snippets', 'total_views')
    
    def has_add_permission(self, request):
        return False
    
    def views_per_snippet(self, obj):
        if obj.total_snippets > 0:
            return round(obj.total_views / obj.total_snippets, 2)
        return 0
    views_per_snippet.short_description = 'Views Per Snippet'

@admin.register(SnippetDiff)
class SnippetDiffAdmin(admin.ModelAdmin):
    list_display = ('id', 'source_snippet_link', 'target_snippet_link', 'created_at')
    list_filter = ('created_at',)
    readonly_fields = ('id', 'source_snippet', 'target_snippet', 'diff_content', 'created_at')
    fields = ('source_snippet', 'target_snippet', 'diff_content', 'created_at')
    
    def has_add_permission(self, request):
        return False
    
    def source_snippet_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.source_snippet.id])
        return mark_safe('<a href="{}">{}</a>'.format(url, obj.source_snippet.id))
    source_snippet_link.short_description = 'Source Snippet'
    
    def target_snippet_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.target_snippet.id])
        return mark_safe('<a href="{}">{}</a>'.format(url, obj.target_snippet.id))
    target_snippet_link.short_description = 'Target Snippet'



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