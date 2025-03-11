from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
from .models import SnippetMetrics

@shared_task
def flush_snippet_metrics():
    today = timezone.now().date()

    snippet_cache_key = f'snippet_metrics_{today}'
    view_cache_key = f'snippet_view_metrics_{today}'

    snippet_count = cache.get(snippet_cache_key, 0)
    view_count = cache.get(view_cache_key, 0)

    if snippet_count or view_count:
        with transaction.atomic():
            obj, created = SnippetMetrics.objects.get_or_create(date=today)
            obj.total_snippets += snippet_count
            obj.total_views += view_count
            obj.save(update_fields=['total_snippets', 'total_views'])

        # Clear cache after saving to DB
        cache.delete(snippet_cache_key)
        cache.delete(view_cache_key)
