from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
from .models import SnippetMetrics, VSCodeExtensionMetrics

@shared_task
def flush_snippet_metrics():
    today = timezone.now().date()

    # Existing snippet and view metrics
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

@shared_task
def flush_vscode_metrics():
    today = timezone.now().date()
    
    # Get all VS Code metrics from cache
    actions_key = f'vscode_actions_{today}'
    selections_key = f'vscode_selections_{today}'
    files_key = f'vscode_files_{today}'
    errors_key = f'vscode_errors_{today}'
    clients_key = f'vscode_clients_{today}'
    
    # Get values from cache
    action_count = cache.get(actions_key, 0)
    selection_count = cache.get(selections_key, 0)
    file_count = cache.get(files_key, 0)
    error_count = cache.get(errors_key, 0)
    client_set = cache.get(clients_key, set())
    
    # Only update if we have data
    if action_count or selection_count or file_count or error_count or client_set:
        with transaction.atomic():
            obj, created = VSCodeExtensionMetrics.objects.get_or_create(date=today)
            
            obj.total_actions += action_count
            obj.selection_shares += selection_count
            obj.file_shares += file_count
            obj.error_count += error_count
            
            # Update unique clients if we have client data
            if client_set:
                obj.unique_clients = len(client_set)
                
            obj.save()
            
        # Clear cache after saving
        cache.delete(actions_key)
        cache.delete(selections_key)
        cache.delete(files_key)
        cache.delete(errors_key)
        cache.delete(clients_key)

@shared_task
def flush_all_metrics():
    """Flush all metrics in one task"""
    flush_snippet_metrics()
    flush_vscode_metrics()