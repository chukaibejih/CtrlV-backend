# analytics_urls.py
from django.urls import path
from .views import (
    AnalyticsDashboardView,
    SnippetAnalyticsView,
    UserBehaviorAnalyticsView,
    VSCodeAnalyticsView,
    PerformanceAnalyticsView,
    RealTimeMetricsView,
    CustomAnalyticsView,
)

urlpatterns = [
    # Main dashboard overview
    path('dashboard/', AnalyticsDashboardView.as_view(), name='analytics-dashboard'),
    
    # Detailed analytics endpoints
    path('snippets/', SnippetAnalyticsView.as_view(), name='snippet-analytics'),
    path('users/', UserBehaviorAnalyticsView.as_view(), name='user-behavior-analytics'),
    path('vscode/', VSCodeAnalyticsView.as_view(), name='vscode-analytics'),
    path('performance/', PerformanceAnalyticsView.as_view(), name='performance-analytics'),
    
    # Real-time metrics
    path('realtime/', RealTimeMetricsView.as_view(), name='realtime-metrics'),
    
    # Custom analytics queries
    path('custom/', CustomAnalyticsView.as_view(), name='custom-analytics'),
]