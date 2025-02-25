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
        access_token = request.query_params.get('token')
        
        try:
            snippet = Snippet.objects.get(
                id=snippet_id,
                access_token=access_token
            )
        except Snippet.DoesNotExist:
            return Response(
                {'error': 'Invalid snippet or access token'},
                status=status.HTTP_404_NOT_FOUND
            )

        if snippet.is_expired:
            return Response(
                {'error': 'Snippet has expired'},
                status=status.HTTP_404_NOT_FOUND
            )

        if snippet.one_time_view and snippet.view_count > 0:
            return Response(
                {'error': 'This snippet has already been viewed'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        snippet.increment_view_count()

        # Update metrics
        SnippetMetrics.record_snippet_view()

        serializer = SnippetSerializer(snippet)
        return Response(serializer.data)


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