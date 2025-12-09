from django.urls import path
from .views import (
    MonthlyStatsView,
    PublicFeedView,
    PublicSnippetRetrieveView, 
    SnippetCreateView, 
    SnippetRetrieveView, 
    SnippetStatsView, 
    TimeSeriesStatsView,
    SnippetVersionView,
    SnippetDiffView,
    VSCodeMetricsView,
    SnippetCommentView,
    SnippetCommentDeleteView,
    SnippetReactionView,
    SnippetDiffQueryView,
)

urlpatterns = [
    path('', SnippetCreateView.as_view(), name='snippet-create'),
    path('<uuid:snippet_id>/', SnippetRetrieveView.as_view(), name='snippet-retrieve'),
    path('stats/', SnippetStatsView.as_view(), name='snippet-stats'),
    path('stats/monthly/', MonthlyStatsView.as_view(), name='monthly-stats'),
    path('stats/timeseries/', TimeSeriesStatsView.as_view(), name='timeseries-stats'),
    path('metrics/vscode/', VSCodeMetricsView.as_view(), name='vscode-metrics'),
    path('<uuid:snippet_id>/versions/', SnippetVersionView.as_view(), name='snippet-versions'),
    path('diff/<uuid:source_id>/<uuid:target_id>/', SnippetDiffView.as_view(), name='snippet-diff'),
    path('<uuid:snippet_id>/diff/', SnippetDiffQueryView.as_view(), name='snippet-diff-query'),
    path('<uuid:snippet_id>/comments/', SnippetCommentView.as_view(), name='snippet-comments'),
    path('<uuid:snippet_id>/comments/<uuid:comment_id>/', SnippetCommentDeleteView.as_view(), name='snippet-comment-delete'),
    path('<uuid:snippet_id>/reactions/', SnippetReactionView.as_view(), name='snippet-reactions'),
    path('public/', PublicFeedView.as_view(), name='public-feed'),
    path('public/<uuid:snippet_id>/', PublicSnippetRetrieveView.as_view(), name='public-snippet-retrieve'),
]
