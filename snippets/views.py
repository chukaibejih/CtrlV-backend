from datetime import timedelta
import hashlib
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import models
from django.shortcuts import get_object_or_404
from .models import Snippet, SnippetMetrics, SnippetView
from .serializers import SnippetSerializer, SnippetViewSerializer
from django.core.cache import cache
from django.db import transaction

class SnippetCreateView(APIView):
    def post(self, request):
        serializer = SnippetSerializer(data=request.data)
        if serializer.is_valid():
            snippet = serializer.save()
            
            # Update metrics
            SnippetMetrics.record_snippet_creation()

            return Response({
                'id': snippet.id,
                'access_token': snippet.access_token,
                'sharing_url': snippet.get_sharing_url(request.build_absolute_uri('/')[:-1])
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SnippetRetrieveView(APIView):
    def get(self, request, snippet_id):
        # Create a cache key for this specific snippet
        cache_key = f'snippet:{snippet_id}'
        
        # Try to get from cache first
        cached_snippet = cache.get(cache_key)
        if cached_snippet:
            return Response(cached_snippet)
        
        try:
            with transaction.atomic():
                snippet = (
                    Snippet.objects
                    .select_related()
                    .only(
                        'id', 'content', 'language', 'created_at', 
                        'expires_at', 'view_count', 'one_time_view',
                        'access_token'
                    )
                    .get(
                        id=snippet_id,
                        access_token=request.query_params.get('token')
                    )
                )
                
                # Validate snippet conditions
                if snippet.is_expired:
                    # Invalidate cache for expired snippet
                    cache.delete(cache_key)
                    return Response(
                        {'error': 'Snippet has expired'},
                        status=status.HTTP_404_NOT_FOUND
                    )

                if snippet.one_time_view and snippet.view_count > 0:
                    # Invalidate cache for one-time viewed snippet
                    cache.delete(cache_key)
                    return Response(
                        {'error': 'This snippet has already been viewed'},
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                # Increment view count using F() expression
                Snippet.objects.filter(id=snippet_id).update(view_count=models.F('view_count') + 1)
                
                # Refresh the snippet to get the updated view count
                snippet.refresh_from_db()
                
                # Batch update metrics
                SnippetMetrics.record_snippet_view()
                
                # Serialize the result
                serializer = SnippetSerializer(snippet)
                serialized_data = serializer.data
                
                # Cache the updated snippet
                # If it's a one-time view, don't cache or set very short timeout
                if snippet.one_time_view:
                    cache_timeout = 10  # Very short cache for one-time view
                else:
                    cache_timeout = 300  # 5 minutes for regular snippets
                
                cache.set(cache_key, serialized_data, timeout=cache_timeout)
                
                return Response(serialized_data)
        
        except Snippet.DoesNotExist:
            # Ensure no stale cache remains
            cache.delete(cache_key)
            return Response(
                {'error': 'Invalid snippet or access token'},
                status=status.HTTP_404_NOT_FOUND
            )


class SnippetStatsView(APIView):
    def get(self, request):
        total_snippets = Snippet.objects.count()
        active_snippets = Snippet.objects.filter(
            expires_at__gt=timezone.now()
        ).count()
        
        language_stats = (
            Snippet.objects
            .filter(expires_at__gt=timezone.now())
            .values('language')
            .annotate(count=models.Count('id'))
        )
        
        return Response({
            'total_snippets': total_snippets,
            'active_snippets': active_snippets,
            'language_stats': language_stats
        })
    

class MonthlyStatsView(APIView):
    def get(self, request):
        start_date = timezone.now().replace(day=1).date()  # First day of current month
        total_snippets = SnippetMetrics.objects.filter(date__gte=start_date).aggregate(models.Sum('total_snippets'))['total_snippets__sum'] or 0
        total_views = SnippetMetrics.objects.filter(date__gte=start_date).aggregate(models.Sum('total_views'))['total_views__sum'] or 0

        return Response({
            'total_snippets_this_month': total_snippets,
            'total_views_this_month': total_views,
        })


class TimeSeriesStatsView(APIView):
    def get(self, request):
        # Get period from query params (daily, weekly, monthly)
        period = request.query_params.get('period', 'monthly')
        
        # Calculate appropriate date ranges
        now = timezone.now()
        if period == 'daily':
            # Last 30 days
            start_date = (now - timedelta(days=30)).date()
            date_trunc = 'day'
            date_format = '%Y-%m-%d'
        elif period == 'weekly':
            # Last 12 weeks
            start_date = (now - timedelta(weeks=12)).date()
            date_trunc = 'week'
            date_format = '%Y-%U'
        else:  # monthly
            # Last 12 months
            start_date = (now - timedelta(days=365)).date()
            date_trunc = 'month'
            date_format = '%Y-%m'
        
        # Use Django's database functions for date manipulation
        from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, Cast
        from django.db.models import CharField
        
        # Select the appropriate truncation function
        if date_trunc == 'day':
            trunc_func = TruncDay('date')
        elif date_trunc == 'week':
            trunc_func = TruncWeek('date')
        else:
            trunc_func = TruncMonth('date')
        
        # Get time series data
        metrics = (SnippetMetrics.objects
                  .filter(date__gte=start_date)
                  .annotate(period=Cast(trunc_func, CharField()))
                  .values('period')
                  .annotate(
                      snippets=models.Sum('total_snippets'),
                      views=models.Sum('total_views')
                  )
                  .order_by('period'))
        
        # Calculate engagement ratio (views per snippet)
        for item in metrics:
            item['engagement_ratio'] = round(item['views'] / item['snippets'], 2) if item['snippets'] > 0 else 0
        
        return Response({
            'period': period,
            'data': metrics
        })