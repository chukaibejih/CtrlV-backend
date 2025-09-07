from datetime import timedelta
import hashlib
import difflib
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from .models import Snippet, SnippetMetrics, SnippetView, SnippetDiff, VSCodeExtensionMetrics, VSCodeTelemetryEvent
from .serializers import (
    PublicSnippetSerializer, SnippetSerializer, SnippetViewSerializer, SnippetDiffSerializer,
    SnippetPasswordCheckSerializer, SnippetVersionSerializer
)
from rest_framework.pagination import PageNumberPagination

class PublicFeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50
    
class SnippetCreateView(APIView):
    def post(self, request):
        serializer = SnippetSerializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        snippet = serializer.save()
        
        # Update metrics
        SnippetMetrics.record_snippet_creation()
        print(snippet.get_sharing_url(request.build_absolute_uri('/')[:-1]))

        return Response({
            'id': snippet.id,
            'access_token': snippet.access_token,
            'sharing_url': snippet.get_sharing_url(request.build_absolute_uri('/')[:-1])
        }, status=status.HTTP_201_CREATED)


class SnippetRetrieveView(APIView):
    def get(self, request, snippet_id):
        # Create a cache key for this specific snippet
        access_token = request.query_params.get('token')
        verified = request.query_params.get('verified')
        
        try:
            # Handle both regular and verified public snippets
            if verified == 'true':
                # For verified public snippets, check if it's public
                snippet = Snippet.objects.get(
                    id=snippet_id,
                    access_token=access_token,
                    is_public=True
                )
            else:
                # Regular snippet access
                snippet = Snippet.objects.get(
                    id=snippet_id,
                    access_token=access_token
                )
        except Snippet.DoesNotExist:
            return Response(
                {'error': 'Invalid snippet or access token'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate snippet conditions
        if snippet.is_expired:
            return Response(
                {'error': 'Snippet has expired'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Handle one-time view snippets
        if snippet.one_time_view and snippet.view_count > 0:
            return Response(
                {'error': 'This snippet has already been viewed'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # If the snippet is password-protected, verify password first
        # Only require verification if verified=True is not in query params
        if snippet.password_hash and verified != 'true':
            return Response(
                {'requires_password': True},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Record the view
        ip_address = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        # TODO You could add IP geolocation here (using a service like MaxMind GeoIP)
        # location = get_location_from_ip(ip_address)
        location = None
        
        SnippetView.objects.create(
            snippet=snippet,
            ip_hash=ip_hash,
            user_agent=user_agent,
            location=location
        )
        
        # Increment view count
        snippet.increment_view_count()

        # Update metrics
        SnippetMetrics.record_snippet_view()
        
        # If the snippet is encrypted and verified, automatically decrypt it
        if snippet.is_encrypted and verified == 'true':
            snippet.decrypt_content()
            
        
        # Check if this snippet has versions and fetch them
        versions = None
        if snippet.parent_snippet or Snippet.objects.filter(parent_snippet=snippet).exists():
            versions_queryset = snippet.get_all_versions()
            versions = SnippetVersionSerializer(versions_queryset, many=True).data

        serializer = SnippetSerializer(snippet)
        response_data = serializer.data
        
        # Add versions information if available
        if versions:
            response_data['versions'] = versions
            
        return Response(response_data)

    # To handle password verification
    def post(self, request, snippet_id):
        action = request.data.get('action')
        
        if action == 'check_password':
            serializer = SnippetPasswordCheckSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
            password = serializer.validated_data['password']
            
            try:
                snippet = Snippet.objects.get(id=snippet_id)
            except Snippet.DoesNotExist:
                return Response(
                    {'error': 'Invalid snippet'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
            if snippet.check_password(password):
                # If the snippet is encrypted, decrypt it right now with the password
                if snippet.is_encrypted:
                    success = snippet.decrypt_content()
                    if not success:
                        return Response(
                            {'error': 'Error decrypting content'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                
                # Return decrypted content if it was encrypted
                if snippet.is_encrypted:
                    serializer = SnippetSerializer(snippet)
                    return Response({
                        'verified': True,
                        'decrypted': True,
                        **serializer.data
                    })
                else:
                    # Just return verification status if not encrypted
                    return Response({'verified': True})
            else:
                return Response(
                    {'error': 'Invalid password'},
                    status=status.HTTP_403_FORBIDDEN
                )
                
        elif action == 'decrypt':
            # This action is now deprecated since we'll decrypt automatically
            # in the check_password action, but kept for backward compatibility
            serializer = SnippetPasswordCheckSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
            password = serializer.validated_data['password']
            
            try:
                snippet = Snippet.objects.get(id=snippet_id)
            except Snippet.DoesNotExist:
                return Response(
                    {'error': 'Invalid snippet'},
                    status=status.HTTP_404_NOT_FOUND
                )
                
            if snippet.is_encrypted:
                success = snippet.decrypt_content()
                if success:
                    serializer = SnippetSerializer(snippet)
                    return Response(serializer.data)
                else:
                    return Response(
                        {'error': 'Invalid password for decryption'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            else:
                return Response(
                    {'error': 'Snippet is not encrypted'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return Response(
            {'error': 'Invalid action'},
            status=status.HTTP_400_BAD_REQUEST
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


class SnippetVersionView(APIView):
    def post(self, request, snippet_id):
        """Create a new version of a snippet"""
        try:
            original_snippet = Snippet.objects.get(id=snippet_id)
        except Snippet.DoesNotExist:
            return Response(
                {'error': 'Original snippet not found'},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Update request data to include parent ID
        request_data = request.data.copy()
        request_data['parent_id'] = str(original_snippet.id)
        
        serializer = SnippetSerializer(data=request_data, context={'request': request})
        if serializer.is_valid():
            new_snippet = serializer.save()
            
            # Generate diff
            source_lines = original_snippet.content.splitlines()
            target_lines = new_snippet.content.splitlines()
            diff = difflib.unified_diff(
                source_lines,
                target_lines,
                fromfile=f'v{original_snippet.version}',
                tofile=f'v{new_snippet.version}',
                lineterm=''
            )
            diff_text = '\n'.join(diff)
            
            # Store the diff
            SnippetDiff.objects.create(
                source_snippet=original_snippet,
                target_snippet=new_snippet,
                diff_content=diff_text
            )
            
            # Update metrics
            SnippetMetrics.record_snippet_creation()
            
            return Response({
                'id': new_snippet.id,
                'access_token': new_snippet.access_token,
                'sharing_url': new_snippet.get_sharing_url(request.build_absolute_uri('/')[:-1]),
                'version': new_snippet.version,
                'diff': diff_text
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get(self, request, snippet_id):
        """Get all versions of a snippet"""
        try:
            snippet = Snippet.objects.get(id=snippet_id)
        except Snippet.DoesNotExist:
            return Response(
                {'error': 'Snippet not found'},
                status=status.HTTP_404_NOT_FOUND
            )
            
        versions = snippet.get_all_versions()
        serializer = SnippetVersionSerializer(versions, many=True)
        
        return Response(serializer.data)


class SnippetDiffView(APIView):
    def get(self, request, source_id, target_id):
        """Get diff between two snippet versions"""
        try:
            source = Snippet.objects.get(id=source_id)
            target = Snippet.objects.get(id=target_id)
        except Snippet.DoesNotExist:
            return Response(
                {'error': 'One or both snippets not found'},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Check if diff already exists
        try:
            diff = SnippetDiff.objects.get(
                source_snippet=source,
                target_snippet=target
            )
        except SnippetDiff.DoesNotExist:
            # Generate new diff
            source_lines = source.content.splitlines()
            target_lines = target.content.splitlines()
            diff_generator = difflib.unified_diff(
                source_lines,
                target_lines,
                fromfile=f'v{source.version}',
                tofile=f'v{target.version}',
                lineterm=''
            )
            diff_text = '\n'.join(diff_generator)
            
            # Store the diff
            diff = SnippetDiff.objects.create(
                source_snippet=source,
                target_snippet=target,
                diff_content=diff_text
            )
        
        serializer = SnippetDiffSerializer(diff)
        return Response(serializer.data)


class VSCodeMetricsView(APIView):
    def post(self, request):
        print("=== Incoming VSCode Metrics Request ===")
        print(f"Content-Type: {request.content_type}")
        print(f"Data: {request.data}")
        
        event_type = request.data.get('event_type')
        event_name = request.data.get('event_name')
        client_id = request.data.get('client_id')
        is_error = event_name == 'shareError'
        
        try:
            # Store the detailed telemetry event asynchronously
            transaction.on_commit(lambda: self._store_telemetry_event(request.data))
            
            # Record the aggregated metric as before
            VSCodeExtensionMetrics.record_action(event_name, client_id, is_error)
        except Exception as e:
            # Log the error but still return success (telemetry should be non-blocking)
            print(f"Error processing metrics: {e}")
            
        return Response({'status': 'received'}, status=status.HTTP_202_ACCEPTED)
    
    def _store_telemetry_event(self, data):
        """Store the detailed telemetry event (called after transaction commit)"""
        try:
            VSCodeTelemetryEvent.create_from_request(data)
        except Exception as e:
            # Log the error but don't propagate (telemetry errors shouldn't interrupt the user)
            print(f"Failed to store detailed telemetry: {e}")
            

class PublicFeedView(APIView):
    """
    Public feed endpoint for discovering public snippets
    GET /api/v1/snippets/public/
    """
    pagination_class = PublicFeedPagination
    
    def get(self, request):
        # Get active public snippets
        queryset = Snippet.objects.filter(
            is_public=True,
            expires_at__gt=timezone.now()
        ).exclude(
            one_time_view=True,
            is_consumed=True
        ).select_related().order_by('-created_at')
        
        # Apply pagination
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = PublicSnippetSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        # Fallback without pagination
        serializer = PublicSnippetSerializer(queryset[:20], many=True)
        return Response(serializer.data)

class PublicSnippetRetrieveView(APIView):
    """
    Retrieve a specific public snippet
    GET /api/v1/snippets/public/{snippet_id}/
    """
    def get(self, request, snippet_id):
        try:
            snippet = Snippet.objects.get(
                id=snippet_id,
                is_public=True,
                expires_at__gt=timezone.now()
            )
            if snippet.one_time_view and snippet.is_consumed:
                return Response({
                    'error': 'This one-time snippet has already been viewed',
                    'error_code': 'SNIPPET_CONSUMED'
                }, status=status.HTTP_404_NOT_FOUND)

        except Snippet.DoesNotExist:
            return Response(
                {'error': 'Public snippet not found or has expired'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if password protected
        if snippet.password_hash:
            password = request.data.get('password') if request.method == 'POST' else None
            
            if not password:
                return Response(
                    {
                        'requires_password': True,
                        'protection_level': snippet.protection_level,
                        'one_time_warning': snippet.one_time_view
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if not snippet.check_password(password):
                return Response(
                    {'error': 'Invalid password'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Decrypt if needed
        if snippet.is_encrypted:
            snippet.decrypt_content()
        
        # Record the view
        ip_address = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        SnippetView.objects.create(
            snippet=snippet,
            ip_hash=ip_hash,
            user_agent=user_agent
        )
        
        # Increment view count
        snippet.increment_view_count()
        
        # # Update metrics
        SnippetMetrics.record_snippet_view()
        
        # # Handle one-time view 
        if snippet.one_time_view:
            snippet.mark_as_consumed()
        
        serializer = SnippetSerializer(snippet)
        return Response(serializer.data)
    
    def post(self, request, snippet_id):
        """Handle password verification for protected public snippets"""
        return self.get(request, snippet_id)