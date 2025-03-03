# admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Snippet, SnippetView, SnippetMetrics, SnippetDiff

class SnippetViewInline(admin.TabularInline):
    model = SnippetView
    extra = 0
    readonly_fields = ('id', 'viewed_at', 'ip_hash', 'user_agent')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False

class VersionInline(admin.TabularInline):
    model = Snippet
    fk_name = 'parent_snippet'
    extra = 0
    readonly_fields = ('id', 'version', 'content', 'language', 'created_at', 'view_count', 'version_link')
    fields = ('version', 'version_link', 'language', 'created_at', 'view_count')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False
        
    def version_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.id])
        return format_html('<a href="{}">View Version</a>', url)
    version_link.short_description = 'View'

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
            return format_html('<pre>{}</pre>', preview)
        return "-"
    diff_preview.short_description = 'Diff Preview'
    
    def target_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.target_snippet.id])
        return format_html('<a href="{}">View Target</a>', url)
    target_link.short_description = 'Target'

@admin.register(Snippet)
class SnippetAdmin(admin.ModelAdmin):
    list_display = ('id', 'language', 'created_at', 'expires_at', 'view_count', 
                   'is_encrypted', 'one_time_view', 'has_password', 'version', 'parent_link')
    list_filter = ('language', 'is_encrypted', 'one_time_view', 'created_at')
    search_fields = ('id', 'content', 'language')
    readonly_fields = ('id', 'access_token', 'created_at', 'view_count', 'parent_snippet', 'version', 
                      'content_preview', 'expires_in', 'sharing_url')
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
            'fields': ('view_count', 'sharing_url')
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
        return format_html('<pre>{}</pre>', preview)
    content_preview.short_description = 'Content Preview'
    
    def expires_in(self, obj):
        from django.utils import timezone
        if obj.expires_at <= timezone.now():
            return "Expired"
        delta = obj.expires_at - timezone.now()
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
        base_url = "https://yoursite.com"  # Replace with your actual base URL
        url = obj.get_sharing_url(base_url)
        return format_html('<a href="{0}" target="_blank">{0}</a>', url)
    sharing_url.short_description = 'Sharing URL'
    
    def parent_link(self, obj):
        if obj.parent_snippet:
            url = reverse('admin:snippets_snippet_change', args=[obj.parent_snippet.id])
            return format_html('<a href="{}">View Parent</a>', url)
        return "-"
    parent_link.short_description = 'Parent'
    
    def save_model(self, request, obj, form, change):
        # Handle password protection
        if 'password' in form.data and form.data['password']:
            obj.set_password(form.data['password'])
        super().save_model(request, obj, form, change)

@admin.register(SnippetView)
class SnippetViewAdmin(admin.ModelAdmin):
    list_display = ('id', 'snippet_link', 'viewed_at', 'ip_hash', 'user_agent')
    list_filter = ('viewed_at',)
    search_fields = ('ip_hash', 'user_agent')
    readonly_fields = ('id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent')
    
    def has_add_permission(self, request):
        return False
    
    def snippet_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.snippet.id])
        return format_html('<a href="{}">{}</a>', url, obj.snippet.id)
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
        return format_html('<a href="{}">{}</a>', url, obj.source_snippet.id)
    source_snippet_link.short_description = 'Source Snippet'
    
    def target_snippet_link(self, obj):
        url = reverse('admin:snippets_snippet_change', args=[obj.target_snippet.id])
        return format_html('<a href="{}">{}</a>', url, obj.target_snippet.id)
    target_snippet_link.short_description = 'Target Snippet'