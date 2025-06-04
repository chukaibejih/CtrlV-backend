# analytics_serializers.py
from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta


class MetricSerializer(serializers.Serializer):
    """Base serializer for metric data with consistent formatting"""
    value = serializers.FloatField()
    label = serializers.CharField()
    change_percent = serializers.FloatField(required=False, allow_null=True)
    trend = serializers.CharField(required=False)  # 'up', 'down', 'stable'
    formatted_value = serializers.SerializerMethodField()
    
    def get_formatted_value(self, obj):
        """Format numeric values for display"""
        value = obj.get('value', 0)
        if value >= 1_000_000:
            return f"{value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"{value/1_000:.1f}K"
        else:
            return str(int(value))


class TimeSeriesDataSerializer(serializers.Serializer):
    """Serializer for time-series data points"""
    timestamp = serializers.DateTimeField()
    value = serializers.FloatField()
    label = serializers.CharField(required=False)
    metadata = serializers.DictField(required=False)


class LanguageStatsSerializer(serializers.Serializer):
    """Serializer for programming language statistics"""
    language = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.SerializerMethodField()
    avg_views = serializers.FloatField(required=False)
    total_views = serializers.IntegerField(required=False)
    avg_code_length = serializers.FloatField(required=False)
    encrypted_count = serializers.IntegerField(required=False)
    
    def get_percentage(self, obj):
        total = self.context.get('total_count', 1)
        return round((obj['count'] / total) * 100, 1) if total > 0 else 0


class DashboardOverviewSerializer(serializers.Serializer):
    """Main dashboard overview data"""
    overview = serializers.DictField()
    today_metrics = serializers.DictField()
    changes = serializers.DictField()
    popular_languages = LanguageStatsSerializer(many=True)
    quick_stats = serializers.SerializerMethodField()
    
    def get_quick_stats(self, obj):
        overview = obj.get('overview', {})
        today = obj.get('today_metrics', {})
        
        return [
            {
                'title': 'Total Snippets',
                'value': overview.get('total_snippets', 0),
                'icon': 'code',
                'color': 'blue'
            },
            {
                'title': 'Active Snippets',
                'value': overview.get('active_snippets', 0),
                'icon': 'activity',
                'color': 'green'
            },
            {
                'title': 'Total Views',
                'value': overview.get('total_views', 0),
                'icon': 'eye',
                'color': 'purple'
            },
            {
                'title': 'Today\'s Snippets',
                'value': today.get('snippets_created', 0),
                'icon': 'plus-circle',
                'color': 'orange'
            }
        ]


class UserBehaviorSerializer(serializers.Serializer):
    """User behavior analytics data"""
    period = serializers.CharField()
    visitor_metrics = serializers.DictField()
    hourly_patterns = TimeSeriesDataSerializer(many=True)
    location_distribution = serializers.ListField()
    browser_distribution = serializers.ListField()
    engagement_metrics = serializers.SerializerMethodField()
    
    def get_engagement_metrics(self, obj):
        visitor_metrics = obj.get('visitor_metrics', {})
        return {
            'bounce_rate': 100 - visitor_metrics.get('return_rate', 0),
            'avg_session_length': '2.5 min',  # Would calculate from actual data
            'pages_per_session': 1.8,  # Would calculate from actual data
        }


class VSCodeAnalyticsSerializer(serializers.Serializer):
    """VS Code extension analytics"""
    period = serializers.CharField()
    daily_activity = TimeSeriesDataSerializer(many=True)
    event_distribution = serializers.ListField()
    version_distribution = serializers.ListField()
    language_usage = LanguageStatsSerializer(many=True)
    error_analysis = serializers.ListField()
    summary = serializers.DictField()
    performance_insights = serializers.SerializerMethodField()
    
    def get_performance_insights(self, obj):
        summary = obj.get('summary', {})
        return {
            'most_popular_action': 'shareSelectedCode',  # Would derive from data
            'peak_usage_hour': '14:00',  # Would calculate from hourly data
            'reliability_score': max(0, 100 - summary.get('error_rate', 0)),
            'adoption_trend': 'growing'  # Would calculate from time series
        }


class PerformanceMetricsSerializer(serializers.Serializer):
    """System performance metrics"""
    period = serializers.CharField()
    snippet_lifecycle = serializers.DictField()
    content_metrics = serializers.DictField()
    versioning_metrics = serializers.DictField()
    usage_patterns = serializers.DictField()
    optimization_suggestions = serializers.SerializerMethodField()
    
    def get_optimization_suggestions(self, obj):
        lifecycle = obj.get('snippet_lifecycle', {})
        content = obj.get('content_metrics', {})
        
        suggestions = []
        
        if lifecycle.get('never_viewed_count', 0) > 100:
            suggestions.append({
                'type': 'warning',
                'title': 'High unused snippet count',
                'description': 'Consider implementing better discovery mechanisms'
            })
        
        if content.get('encryption_usage_percent', 0) < 10:
            suggestions.append({
                'type': 'info',
                'title': 'Low encryption adoption',
                'description': 'Promote security features to users'
            })
        
        return suggestions


class RealTimeMetricsSerializer(serializers.Serializer):
    """Real-time dashboard metrics"""
    timestamp = serializers.DateTimeField()
    recent_activity = serializers.DictField()
    trending_languages = LanguageStatsSerializer(many=True)
    active_users_estimate = serializers.IntegerField()
    health_metrics = serializers.DictField()
    alerts = serializers.SerializerMethodField()
    
    def get_alerts(self, obj):
        health = obj.get('health_metrics', {})
        alerts = []
        
        error_rate = health.get('error_rate_last_hour', 0)
        if error_rate > 5:
            alerts.append({
                'level': 'error' if error_rate > 10 else 'warning',
                'message': f'High error rate: {error_rate}%',
                'timestamp': timezone.now().isoformat()
            })
        
        return alerts


class CustomAnalyticsSerializer(serializers.Serializer):
    """Custom analytics query results"""
    query_type = serializers.CharField()
    period_days = serializers.IntegerField(required=False)
    results = serializers.ListField()
    summary = serializers.DictField(required=False)
    metadata = serializers.DictField(required=False)


class AnalyticsExportSerializer(serializers.Serializer):
    """Serializer for data export functionality"""
    format = serializers.ChoiceField(choices=['csv', 'json', 'excel'])
    date_range = serializers.DictField()
    metrics = serializers.ListField()
    filters = serializers.DictField(required=False)


class AlertConfigSerializer(serializers.Serializer):
    """Configuration for analytics alerts"""
    metric_name = serializers.CharField()
    threshold_value = serializers.FloatField()
    condition = serializers.ChoiceField(choices=['above', 'below', 'equals'])
    notification_method = serializers.ChoiceField(choices=['email', 'webhook', 'dashboard'])
    is_active = serializers.BooleanField(default=True)


# Response wrapper serializers for consistent API responses
class AnalyticsResponseSerializer(serializers.Serializer):
    """Standard wrapper for all analytics responses"""
    success = serializers.BooleanField(default=True)
    data = serializers.DictField()
    metadata = serializers.DictField(required=False)
    timestamp = serializers.DateTimeField(default=timezone.now)
    cache_info = serializers.DictField(required=False)


class ErrorResponseSerializer(serializers.Serializer):
    """Standard error response format"""
    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    error_code = serializers.CharField(required=False)
    details = serializers.DictField(required=False)
    timestamp = serializers.DateTimeField(default=timezone.now)


# Utility serializers for common data structures
class ChartDataSerializer(serializers.Serializer):
    """Standardized chart data format"""
    chart_type = serializers.ChoiceField(
        choices=['line', 'bar', 'pie', 'doughnut', 'area', 'scatter']
    )
    title = serializers.CharField()
    datasets = serializers.ListField()
    labels = serializers.ListField()
    options = serializers.DictField(required=False)


class TableDataSerializer(serializers.Serializer):
    """Standardized table data format"""
    headers = serializers.ListField()
    rows = serializers.ListField()
    pagination = serializers.DictField(required=False)
    sorting = serializers.DictField(required=False)


class FilterOptionsSerializer(serializers.Serializer):
    """Available filter options for analytics"""
    date_ranges = serializers.ListField()
    languages = serializers.ListField()
    metrics = serializers.ListField()
    custom_filters = serializers.DictField(required=False)