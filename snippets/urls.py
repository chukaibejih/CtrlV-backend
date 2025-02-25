from django.urls import path
from .views import MonthlyStatsView, SnippetCreateView, SnippetRetrieveView, SnippetStatsView, TimeSeriesStatsView

urlpatterns = [
    path('', SnippetCreateView.as_view(), name='snippet-create'),
    path('<uuid:snippet_id>/', SnippetRetrieveView.as_view(), name='snippet-retrieve'),
    path('stats/', SnippetStatsView.as_view(), name='snippet-stats'),
    path('stats/monthly/', MonthlyStatsView.as_view(), name='monthly-stats'),
    path('stats/timeseries/', TimeSeriesStatsView.as_view(), name='timeseries-stats'),
]