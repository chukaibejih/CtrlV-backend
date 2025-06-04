# analytics/views.py - VALIDATED & CORRECTED VERSION

from datetime import timedelta, date
from django.utils import timezone
from django.db import models, connection
from django.db.models import Count, Sum, Avg, Max, Min, F, Q, Case, When, Value
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour, Length, Extract
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from snippets.models import (
    Snippet, SnippetView, SnippetMetrics, VSCodeExtensionMetrics, 
    VSCodeTelemetryEvent, SnippetDiff
)


class AnalyticsDashboardView(APIView):
    """
    Main dashboard overview with key metrics
    """
    def get(self, request):
        now = timezone.now()
        today = now.date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)
        
        # Overview metrics
        total_snippets = Snippet.objects.count()
        active_snippets = Snippet.objects.filter(expires_at__gt=now).count()
        total_views = SnippetView.objects.count()
        
        # Today's metrics
        today_snippets = Snippet.objects.filter(created_at__date=today).count()
        today_views = SnippetView.objects.filter(viewed_at__date=today).count()
        
        # Yesterday comparison
        yesterday_snippets = Snippet.objects.filter(created_at__date=yesterday).count()
        yesterday_views = SnippetView.objects.filter(viewed_at__date=yesterday).count()
        
        # Calculate percentage changes
        snippet_change = self._calculate_percentage_change(today_snippets, yesterday_snippets)
        view_change = self._calculate_percentage_change(today_views, yesterday_views)
        
        # Language popularity (last 7 days)
        popular_languages = list(
            Snippet.objects
            .filter(created_at__date__gte=week_ago)
            .values('language')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # VS Code metrics
        vscode_today = VSCodeTelemetryEvent.objects.filter(
            timestamp__date=today
        ).count()
        
        # Encryption usage
        encrypted_snippets = Snippet.objects.filter(is_encrypted=True).count()
        password_protected = Snippet.objects.filter(
            password_hash__isnull=False
        ).count()
        
        # Average views per snippet
        avg_views = SnippetView.objects.aggregate(
            avg_views=Avg('snippet__view_count')
        )['avg_views'] or 0
        
        return Response({
            'overview': {
                'total_snippets': total_snippets,
                'active_snippets': active_snippets,
                'total_views': total_views,
                'avg_views_per_snippet': round(avg_views, 2),
                'encrypted_snippets': encrypted_snippets,
                'password_protected_snippets': password_protected,
            },
            'today': {
                'snippets_created': today_snippets,
                'views': today_views,
                'vscode_actions': vscode_today,
            },
            'changes': {
                'snippets_change_percent': snippet_change,
                'views_change_percent': view_change,
            },
            'popular_languages': popular_languages,
        })
    
    def _calculate_percentage_change(self, current, previous):
        if previous == 0:
            return 100 if current > 0 else 0
        return round(((current - previous) / previous) * 100, 1)


class SnippetAnalyticsView(APIView):
    """
    Detailed snippet analytics and trends
    """
    def get(self, request):
        period = request.query_params.get('period', '7d')  # 7d, 30d, 90d, all
        
        # Get date range and truncation function
        start_date, trunc_func = self._get_date_range_and_trunc(period)
        
        # Daily/Weekly/Monthly snippet creation trends
        creation_trends = list(
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .annotate(period=trunc_func('created_at'))
            .values('period')
            .annotate(
                count=Count('id'),
                encrypted_count=Count('id', filter=Q(is_encrypted=True)),
                password_protected_count=Count('id', filter=Q(password_hash__isnull=False)),
                one_time_view_count=Count('id', filter=Q(one_time_view=True))
            )
            .order_by('period')
        )
        
        # Language distribution
        language_stats = list(
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .values('language')
            .annotate(
                count=Count('id'),
                avg_views=Avg('view_count'),
                total_views=Sum('view_count')
            )
            .order_by('-count')
        )
        
        # Snippet lifetime analysis
        expired_snippets = Snippet.objects.filter(
            expires_at__lt=timezone.now(),
            created_at__date__gte=start_date
        ).count()
        
        # View patterns
        view_patterns = list(
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .annotate(period=trunc_func('viewed_at'))
            .values('period')
            .annotate(count=Count('id'))
            .order_by('period')
        )
        
        # Top performing snippets
        top_snippets = list(
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .annotate(view_count_actual=Count('views'))
            .order_by('-view_count_actual')[:10]
            .values('id', 'language', 'created_at', 'view_count_actual', 'is_encrypted')
        )
        
        return Response({
            'period': period,
            'creation_trends': creation_trends,
            'language_stats': language_stats,
            'view_patterns': view_patterns,
            'top_snippets': top_snippets,
            'summary': {
                'total_created': sum(item['count'] for item in creation_trends),
                'total_expired': expired_snippets,
                'most_popular_language': language_stats[0]['language'] if language_stats else None,
            }
        })
    
    def _get_date_range_and_trunc(self, period):
        """Helper method to get date range and truncation function"""
        end_date = timezone.now().date()
        
        if period == '7d':
            start_date = end_date - timedelta(days=7)
            trunc_func = TruncDate
        elif period == '30d':
            start_date = end_date - timedelta(days=30)
            trunc_func = TruncDate
        elif period == '90d':
            start_date = end_date - timedelta(days=90)
            trunc_func = TruncWeek
        elif period == 'all':
            # For all time, get the earliest snippet date
            earliest_snippet = Snippet.objects.order_by('created_at').first()
            if earliest_snippet:
                start_date = earliest_snippet.created_at.date()
            else:
                # Fallback if no snippets exist
                start_date = end_date - timedelta(days=365)
            trunc_func = TruncMonth  # Use monthly grouping for all-time data
        else:
            # Default to 7 days
            start_date = end_date - timedelta(days=7)
            trunc_func = TruncDate
        
        return start_date, trunc_func


class UserBehaviorAnalyticsView(APIView):
    """
    User behavior and engagement analytics
    """
    def get(self, request):
        period = request.query_params.get('period', '30d')
        
        # Get date range
        start_date = self._get_start_date(period)
        
        # View patterns by hour of day
        hourly_views = list(
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .extra(select={'hour': 'EXTRACT(hour FROM viewed_at)'})
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
        )
        
        # Geographic distribution (if location data available)
        location_stats = list(
            SnippetView.objects
            .filter(
                viewed_at__date__gte=start_date,
                location__isnull=False
            )
            .exclude(location='')
            .values('location')
            .annotate(count=Count('id'))
            .order_by('-count')[:20]
        )
        
        # Browser distribution using raw SQL
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN user_agent LIKE %s THEN 'Chrome'
                        WHEN user_agent LIKE %s THEN 'Firefox'
                        WHEN user_agent LIKE %s THEN 'Safari'
                        WHEN user_agent LIKE %s THEN 'Edge'
                        ELSE 'Other'
                    END as browser,
                    COUNT(*) as count
                FROM snippet_views 
                WHERE viewed_at >= %s
                GROUP BY browser
                ORDER BY count DESC
            """, ['%Chrome%', '%Firefox%', '%Safari%', '%Edge%', start_date])
            
            browser_results = cursor.fetchall()
            user_agent_stats = [
                {'browser': row[0], 'count': row[1]} 
                for row in browser_results
            ]
        
        # Unique visitors (based on IP hash)
        unique_visitors = (
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .values('ip_hash')
            .distinct()
            .count()
        )
        
        # Return vs new visitors
        returning_visitors = (
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .values('ip_hash')
            .annotate(visit_count=Count('id'))
            .filter(visit_count__gt=1)
            .count()
        )
        
        # One-time view usage
        one_time_views = (
            Snippet.objects
            .filter(
                created_at__date__gte=start_date,
                one_time_view=True
            )
            .aggregate(
                total=Count('id'),
                viewed=Count('id', filter=Q(view_count__gt=0))
            )
        )
        
        return Response({
            'period': period,
            'hourly_patterns': hourly_views,
            'location_distribution': location_stats,
            'browser_distribution': user_agent_stats,
            'visitor_metrics': {
                'unique_visitors': unique_visitors,
                'returning_visitors': returning_visitors,
                'new_visitors': unique_visitors - returning_visitors,
                'return_rate': round((returning_visitors / unique_visitors * 100), 2) if unique_visitors > 0 else 0
            },
            'one_time_view_stats': {
                'total_one_time_snippets': one_time_views['total'] or 0,
                'viewed_one_time_snippets': one_time_views['viewed'] or 0,
                'usage_rate': round((one_time_views['viewed'] / one_time_views['total'] * 100), 2) if one_time_views['total'] else 0
            }
        })
    
    def _get_start_date(self, period):
        """Helper method to get start date"""
        end_date = timezone.now().date()
        
        if period == '7d':
            return end_date - timedelta(days=7)
        elif period == '30d':
            return end_date - timedelta(days=30)
        elif period == '90d':
            return end_date - timedelta(days=90)
        elif period == 'all':
            # For all time, get the earliest view date
            earliest_view = SnippetView.objects.order_by('viewed_at').first()
            if earliest_view:
                return earliest_view.viewed_at.date()
            else:
                return end_date - timedelta(days=365)
        else:
            return end_date - timedelta(days=30)


class VSCodeAnalyticsView(APIView):
    """
    VS Code extension analytics and metrics
    """
    def get(self, request):
        period = request.query_params.get('period', '30d')
        
        # Get date range and truncation function
        start_date, trunc_func = self._get_date_range_and_trunc(period)
        
        # Daily VS Code activity
        daily_activity = list(
            VSCodeTelemetryEvent.objects
            .filter(timestamp__date__gte=start_date)
            .annotate(date=trunc_func('timestamp'))
            .values('date')
            .annotate(
                total_events=Count('id'),
                unique_clients=Count('client_id', distinct=True),
                selection_shares=Count('id', filter=Q(event_name='shareSelectedCode')),
                file_shares=Count('id', filter=Q(event_name='shareEntireFile')),
                errors=Count('id', filter=Q(event_name='shareError'))
            )
            .order_by('date')
        )
        
        # Event type distribution
        event_distribution = list(
            VSCodeTelemetryEvent.objects
            .filter(timestamp__date__gte=start_date)
            .values('event_name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # VS Code version distribution
        version_distribution = list(
            VSCodeTelemetryEvent.objects
            .filter(
                timestamp__date__gte=start_date,
                vs_code_version__isnull=False
            )
            .values('vs_code_version')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # Language usage in VS Code
        language_usage = list(
            VSCodeTelemetryEvent.objects
            .filter(
                timestamp__date__gte=start_date,
                language__isnull=False
            )
            .values('language')
            .annotate(
                count=Count('id'),
                avg_code_length=Avg('code_length')
            )
            .order_by('-count')[:15]
        )
        
        # Error analysis
        error_analysis = list(
            VSCodeTelemetryEvent.objects
            .filter(
                timestamp__date__gte=start_date,
                event_name='shareError',
                error_message__isnull=False
            )
            .values('error_message')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # Active users and retention
        total_clients = (
            VSCodeTelemetryEvent.objects
            .filter(timestamp__date__gte=start_date)
            .values('client_id')
            .distinct()
            .count()
        )
        
        # Code length statistics
        code_stats = (
            VSCodeTelemetryEvent.objects
            .filter(
                timestamp__date__gte=start_date,
                code_length__isnull=False
            )
            .aggregate(
                avg_length=Avg('code_length'),
                min_length=Min('code_length'),
                max_length=Max('code_length'),
                total_chars_shared=Sum('code_length')
            )
        )
        
        return Response({
            'period': period,
            'daily_activity': daily_activity,
            'event_distribution': event_distribution,
            'version_distribution': version_distribution,
            'language_usage': language_usage,
            'error_analysis': error_analysis,
            'summary': {
                'total_active_clients': total_clients,
                'total_events': sum(item['total_events'] for item in daily_activity),
                'avg_code_length': round(code_stats['avg_length'] or 0, 2),
                'total_characters_shared': code_stats['total_chars_shared'] or 0,
                'error_rate': round(
                    (sum(item['errors'] for item in daily_activity) / 
                     sum(item['total_events'] for item in daily_activity) * 100), 2
                ) if sum(item['total_events'] for item in daily_activity) > 0 else 0
            }
        })
    
    def _get_date_range_and_trunc(self, period):
        """Helper method to get date range and truncation function"""
        end_date = timezone.now().date()
        
        if period == '7d':
            start_date = end_date - timedelta(days=7)
            trunc_func = TruncDate
        elif period == '30d':
            start_date = end_date - timedelta(days=30)
            trunc_func = TruncDate
        elif period == '90d':
            start_date = end_date - timedelta(days=90)
            trunc_func = TruncWeek
        elif period == 'all':
            # For all time, get the earliest event date
            earliest_event = VSCodeTelemetryEvent.objects.order_by('timestamp').first()
            if earliest_event:
                start_date = earliest_event.timestamp.date()
            else:
                start_date = end_date - timedelta(days=365)
            trunc_func = TruncMonth  # Use monthly grouping for all-time data
        else:
            start_date = end_date - timedelta(days=30)
            trunc_func = TruncDate
        
        return start_date, trunc_func


class PerformanceAnalyticsView(APIView):
    """
    System performance and optimization analytics
    """
    def get(self, request):
        period = request.query_params.get('period', '30d')
        
        # FIXED: Use the helper method consistently
        start_date = self._get_start_date(period)
        
        # Snippet lifecycle metrics
        snippet_lifecycle = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .aggregate(
                avg_views_before_expiry=Avg('view_count'),
                never_viewed=Count('id', filter=Q(view_count=0)),
                highly_viewed=Count('id', filter=Q(view_count__gte=10)),
            )
        )
        
        # Calculate average time to first view separately to avoid complex joins
        first_views = (
            SnippetView.objects
            .filter(
                snippet__created_at__date__gte=start_date,
                viewed_at__isnull=False
            )
            .annotate(
                time_to_view=F('viewed_at') - F('snippet__created_at')
            )
            .aggregate(
                avg_time_to_first_view=Avg('time_to_view')
            )
        )
        
        # Add the time calculation to snippet_lifecycle
        snippet_lifecycle.update(first_views)
        
        # Storage and content analysis using proper Length function
        content_analysis = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .aggregate(
                avg_content_length=Avg(Length('content')),
                total_content_size=Sum(Length('content')),
                total_snippets=Count('id'),
                encrypted_count=Count('id', filter=Q(is_encrypted=True))
            )
        )
        
        # Calculate encryption ratio safely
        total_snippets = content_analysis['total_snippets'] or 1
        content_analysis['encrypted_ratio'] = (
            content_analysis['encrypted_count'] * 100.0 / total_snippets
        )
        
        # Version usage analysis - Calculate separately to avoid field lookup errors
        total_versions = Snippet.objects.filter(
            created_at__date__gte=start_date,
            parent_snippet__isnull=False
        ).count()
        
        # Get parent snippets and count their versions
        parent_snippets_with_versions = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .exclude(parent_snippet__isnull=True)
            .values('parent_snippet')
            .annotate(version_count=Count('id'))
            .aggregate(avg_versions=Avg('version_count'))
        )
        
        version_analysis = {
            'total_versions': total_versions,
            'avg_versions_per_parent': parent_snippets_with_versions['avg_versions'] or 0
        }
        
        # Most active times (peak usage)
        peak_hours = list(
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .extra(select={'hour': 'EXTRACT(hour FROM viewed_at)'})
            .values('hour')
            .annotate(views=Count('id'))
            .order_by('-views')[:5]
        )
        
        # Diff generation usage
        diff_usage = SnippetDiff.objects.filter(
            created_at__date__gte=start_date
        ).count()
        
        # Expiration patterns using proper Extract import
        expiration_analysis = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .annotate(
                lifetime_seconds=Extract(
                    F('expires_at') - F('created_at'), 'epoch'
                )
            )
            .aggregate(
                avg_lifetime_seconds=Avg('lifetime_seconds'),
                expired_before_view=Count('id', filter=Q(
                    expires_at__lt=timezone.now(),
                    view_count=0
                ))
            )
        )
        
        # Convert seconds to hours safely
        avg_lifetime_hours = 0
        if expiration_analysis['avg_lifetime_seconds']:
            avg_lifetime_hours = expiration_analysis['avg_lifetime_seconds'] / 3600.0
        
        return Response({
            'period': period,
            'snippet_lifecycle': {
                'avg_views_before_expiry': round(snippet_lifecycle['avg_views_before_expiry'] or 0, 2),
                'never_viewed_count': snippet_lifecycle['never_viewed'] or 0,
                'highly_viewed_count': snippet_lifecycle['highly_viewed'] or 0,
                'avg_time_to_first_view_hours': round(
                    snippet_lifecycle['avg_time_to_first_view'].total_seconds() / 3600, 2
                ) if snippet_lifecycle['avg_time_to_first_view'] else 0
            },
            'content_metrics': {
                'avg_content_length_chars': round(content_analysis['avg_content_length'] or 0, 2),
                'total_content_size_mb': round((content_analysis['total_content_size'] or 0) / (1024 * 1024), 2),
                'encryption_usage_percent': round(content_analysis['encrypted_ratio'] or 0, 2)
            },
            'versioning_metrics': {
                'total_versions_created': version_analysis['total_versions'],
                'diffs_generated': diff_usage,
                'avg_versions_per_snippet': round(version_analysis['avg_versions_per_parent'] or 0, 2)
            },
            'usage_patterns': {
                'peak_hours': peak_hours,
                'avg_snippet_lifetime_hours': round(avg_lifetime_hours, 2),
                'expired_before_view': expiration_analysis['expired_before_view'] or 0
            }
        })

    def _get_start_date(self, period):
        """Helper method to get start date"""
        end_date = timezone.now().date()
        
        if period == '7d':
            return end_date - timedelta(days=7)
        elif period == '30d':
            return end_date - timedelta(days=30)
        elif period == '90d':
            return end_date - timedelta(days=90)
        elif period == 'all':
            # For all time, get the earliest snippet date
            earliest_snippet = Snippet.objects.order_by('created_at').first()
            if earliest_snippet:
                return earliest_snippet.created_at.date()
            else:
                return end_date - timedelta(days=365)
        else:
            return end_date - timedelta(days=30)


class RealTimeMetricsView(APIView):
    """
    Real-time metrics for live dashboard updates
    """
    def get(self, request):
        now = timezone.now()
        last_hour = now - timedelta(hours=1)
        last_24h = now - timedelta(hours=24)
        
        # Last hour activity
        recent_activity = {
            'snippets_created_last_hour': Snippet.objects.filter(
                created_at__gte=last_hour
            ).count(),
            'views_last_hour': SnippetView.objects.filter(
                viewed_at__gte=last_hour
            ).count(),
            'vscode_events_last_hour': VSCodeTelemetryEvent.objects.filter(
                timestamp__gte=last_hour
            ).count(),
        }
        
        # Real-time language trends (last 24h)
        trending_languages = list(
            Snippet.objects
            .filter(created_at__gte=last_24h)
            .values('language')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        
        # Active users approximation (unique IPs in last hour)
        active_users = (
            SnippetView.objects
            .filter(viewed_at__gte=last_hour)
            .values('ip_hash')
            .distinct()
            .count()
        )
        
        # System health indicators
        health_metrics = {
            'total_active_snippets': Snippet.objects.filter(
                expires_at__gt=now
            ).count(),
            'error_rate_last_hour': 0,  # Calculate from VS Code errors
            'avg_response_time': 'N/A',  # Would require request logging
        }
        
        # Calculate error rate
        vscode_events_last_hour = VSCodeTelemetryEvent.objects.filter(
            timestamp__gte=last_hour
        )
        total_events = vscode_events_last_hour.count()
        error_events = vscode_events_last_hour.filter(event_name='shareError').count()
        
        if total_events > 0:
            health_metrics['error_rate_last_hour'] = round((error_events / total_events) * 100, 2)
        
        return Response({
            'timestamp': now.isoformat(),
            'recent_activity': recent_activity,
            'trending_languages': trending_languages,
            'active_users_estimate': active_users,
            'health_metrics': health_metrics,
        })


class CustomAnalyticsView(APIView):
    """
    Custom analytics endpoint for specific queries
    """
    def post(self, request):
        query_type = request.data.get('query_type')
        filters = request.data.get('filters', {})
        
        if query_type == 'language_performance':
            return self._language_performance_analysis(filters)
        elif query_type == 'user_retention':
            return self._user_retention_analysis(filters)
        elif query_type == 'content_analysis':
            return self._content_analysis(filters)
        else:
            return Response(
                {'error': 'Invalid query type'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def _language_performance_analysis(self, filters):
        period_days = filters.get('period_days', 30)
        start_date = timezone.now().date() - timedelta(days=period_days)
        
        language_performance = list(
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .values('language')
            .annotate(
                total_snippets=Count('id'),
                total_views=Sum('view_count'),
                avg_views=Avg('view_count'),
                engagement_rate=Avg('view_count') / 1.0,  # Normalize as needed
                encrypted_count=Count('id', filter=Q(is_encrypted=True)),
                version_count=Count('id', filter=Q(parent_snippet__isnull=False))
            )
            .order_by('-total_views')
        )
        
        return Response({
            'query_type': 'language_performance',
            'period_days': period_days,
            'results': language_performance
        })
    
    def _user_retention_analysis(self, filters):
        period_days = filters.get('period_days', 30)
        start_date = timezone.now().date() - timedelta(days=period_days)
        
        # Analyze user return patterns based on IP hashes
        user_patterns = (
            SnippetView.objects
            .filter(viewed_at__date__gte=start_date)
            .values('ip_hash')
            .annotate(
                total_views=Count('id'),
                first_visit=Min('viewed_at'),
                last_visit=Max('viewed_at'),
                unique_snippets=Count('snippet', distinct=True)
            )
            .annotate(
                visit_span_days=Case(
                    When(
                        first_visit=F('last_visit'),
                        then=Value(0)
                    ),
                    default=(F('last_visit') - F('first_visit')) / timedelta(days=1),
                    output_field=models.FloatField()
                )
            )
        )
        
        # Aggregate retention metrics
        retention_summary = user_patterns.aggregate(
            total_users=Count('ip_hash'),
            avg_views_per_user=Avg('total_views'),
            avg_visit_span=Avg('visit_span_days'),
            returning_users=Count('ip_hash', filter=Q(total_views__gt=1))
        )
        
        return Response({
            'query_type': 'user_retention',
            'period_days': period_days,
            'summary': retention_summary,
            'user_segments': {
                'one_time_users': user_patterns.filter(total_views=1).count(),
                'casual_users': user_patterns.filter(total_views__range=[2, 5]).count(),
                'regular_users': user_patterns.filter(total_views__range=[6, 15]).count(),
                'power_users': user_patterns.filter(total_views__gt=15).count
            }
        })
    
    def _content_analysis(self, filters):
        period_days = filters.get('period_days', 30)
        start_date = timezone.now().date() - timedelta(days=period_days)
        
        content_metrics = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .annotate(
                content_length=Length('content'),
                lines_count=Value(1)  # Would need custom function to count lines
            )
            .aggregate(
                total_snippets=Count('id'),
                avg_length=Avg('content_length'),
                min_length=Min('content_length'),
                max_length=Max('content_length'),
                total_characters=Sum('content_length'),
                encrypted_ratio=Count('id', filter=Q(is_encrypted=True)) * 100.0 / Count('id')
            )
        )
        
        # Length distribution buckets
        length_buckets = (
            Snippet.objects
            .filter(created_at__date__gte=start_date)
            .annotate(content_length=Length('content'))
            .aggregate(
                very_short=Count('id', filter=Q(content_length__lt=100)),
                short=Count('id', filter=Q(content_length__range=[100, 500])),
                medium=Count('id', filter=Q(content_length__range=[501, 2000])),
                long=Count('id', filter=Q(content_length__range=[2001, 10000])),
                very_long=Count('id', filter=Q(content_length__gt=10000))
            )
        )
        
        return Response({
            'query_type': 'content_analysis',
            'period_days': period_days,
            'content_metrics': content_metrics,
            'length_distribution': length_buckets
        })