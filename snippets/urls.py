from django.urls import path
from .views import SnippetCreateView, SnippetRetrieveView, SnippetStatsView

urlpatterns = [
    path('', SnippetCreateView.as_view(), name='snippet-create'),
    path('<uuid:snippet_id>/', SnippetRetrieveView.as_view(), name='snippet-retrieve'),
    path('stats/', SnippetStatsView.as_view(), name='snippet-stats'),
]