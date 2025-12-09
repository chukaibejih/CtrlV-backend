from datetime import timedelta
import hashlib
import difflib
import re
import secrets
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from .models import (
    Snippet, SnippetMetrics, SnippetView, SnippetDiff,
    VSCodeExtensionMetrics, VSCodeTelemetryEvent,
    SnippetComment, SnippetReaction, SecretScanLog
)
from .serializers import (
    PublicSnippetSerializer, SnippetSerializer, SnippetViewSerializer, SnippetDiffSerializer,
    SnippetPasswordCheckSerializer, SnippetVersionSerializer,
    SnippetCommentSerializer, ReactionRequestSerializer
)
from rest_framework.pagination import PageNumberPagination

SECRET_SCAN_POLICY = {
    "block": False,
    "requires_confirm": True,
}

SECRET_SCAN_RULES = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), "high"),
    ("aws_secret", re.compile(r"(?i)aws(.{0,20})?(secret|access).{0,3}['\"][0-9a-zA-Z\/+]{40}"), "high"),
    ("gh_pat", re.compile(r"ghp_[0-9A-Za-z]{36}"), "high"),
    ("generic_token", re.compile(r"(api[_-]?key|token|secret)[\"'\\s:=]+[A-Za-z0-9\\-_]{16,}"), "medium"),
]


def scan_secrets(content: str):
    """Return warnings for potential secrets."""
    warnings = []
    snippet_preview = content or ""
    for rule_name, pattern, severity in SECRET_SCAN_RULES:
        match = pattern.search(snippet_preview)
        if match:
            fragment = match.group(0)
            warnings.append({
                "type": rule_name,
                "severity": severity,
                "matched": fragment[:64],
            })
    return warnings


def reaction_summary(snippet):
    """Return reaction summary as {type: count}."""
    summary = {r.reaction_type: r.count for r in SnippetReaction.objects.filter(snippet=snippet)}
    return summary


def rate_limit_exceeded(key: str, limit: int, window_seconds: int) -> bool:
    """Simple per-key counter with TTL to limit abuse."""
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, window_seconds)
        return False
    if current >= limit:
        return True
    cache.incr(key)
    return False

class PublicFeedPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50
    
class SnippetCreateView(APIView):
    def post(self, request):
        serializer = SnippetSerializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Secret scan before creation
        content = serializer.validated_data.get('content', '')
        warnings = scan_secrets(content)
        if warnings:
            if SECRET_SCAN_POLICY.get("block"):
                return Response(
                    {"error": "secret_scan_blocked", "warnings": warnings},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if SECRET_SCAN_POLICY.get("requires_confirm") and not request.data.get('confirm_scan'):
                return Response(
                    {"requires_confirm": True, "warnings": warnings},
                    status=status.HTTP_400_BAD_REQUEST
                )

        snippet = serializer.save()
        
        # Update metrics
        SnippetMetrics.record_snippet_creation()
        print(snippet.get_sharing_url(request.build_absolute_uri('/')[:-1]))

        # Audit scan results if present
        if warnings:
            SecretScanLog.objects.bulk_create([
                SecretScanLog(
                    snippet=snippet,
                    rule_type=warn["type"],
                    severity=warn["severity"],
                    matched_fragment=warn["matched"]
                ) for warn in warnings
            ])

        return Response({
            'id': snippet.id,
            'access_token': snippet.access_token,
            'sharing_url': snippet.get_sharing_url(request.build_absolute_uri('/')[:-1]),
            'warnings': warnings,
            'remaining_views': snippet.remaining_views,
            'scan_status': 'warned' if warnings else 'clean',
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

        # Handle max view caps
        if snippet.max_views is not None and snippet.view_count >= snippet.max_views:
            return Response(
                {'error': 'This snippet has reached its view limit'},
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

        # Mark consumed if limits reached
        if snippet.one_time_view or (snippet.max_views is not None and snippet.view_count >= snippet.max_views):
            snippet.mark_as_consumed()
        
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
        
        response_data['scan_status'] = 'warned' if snippet.scan_logs.exists() else 'clean'
            
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
            if snippet.max_views is not None and snippet.view_count >= snippet.max_views:
                return Response({
                    'error': 'Snippet has reached its view limit',
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
        if snippet.one_time_view or (snippet.max_views is not None and snippet.view_count >= snippet.max_views):
            snippet.mark_as_consumed()
        
        serializer = SnippetSerializer(snippet)
        return Response(serializer.data)
    
    def post(self, request, snippet_id):
        """Handle password verification for protected public snippets"""
        return self.get(request, snippet_id)


class SnippetCommentView(APIView):
    """Create/list comments for a snippet (no auth, rate-limited)."""
    def get(self, request, snippet_id):
        snippet = get_object_or_404(Snippet, id=snippet_id)
        if snippet.is_expired:
            return Response({'error': 'Snippet has expired'}, status=status.HTTP_404_NOT_FOUND)
        if not snippet.allow_comments:
            return Response({'error': 'Comments disabled for this snippet'}, status=status.HTTP_403_FORBIDDEN)

        comments_qs = SnippetComment.objects.filter(snippet=snippet).order_by('-created_at')[:200]
        serialized = SnippetCommentSerializer(comments_qs, many=True).data
        for item in serialized:
            item.pop('delete_token', None)
        return Response({
            'comments': serialized,
            'reactions': reaction_summary(snippet)
        })

    def post(self, request, snippet_id):
        snippet = get_object_or_404(Snippet, id=snippet_id)
        if snippet.is_expired:
            return Response({'error': 'Snippet has expired'}, status=status.HTTP_404_NOT_FOUND)
        if not snippet.allow_comments:
            return Response({'error': 'Comments disabled for this snippet'}, status=status.HTTP_403_FORBIDDEN)

        ip_address = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()

        if rate_limit_exceeded(f"comment_rate:{ip_hash}", limit=5, window_seconds=60):
            return Response({'error': 'Too many comments, slow down.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = SnippetCommentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        delete_token = secrets.token_urlsafe(24)
        comment = SnippetComment.objects.create(
            snippet=snippet,
            content=serializer.validated_data['content'],
            display_name=serializer.validated_data.get('display_name') or None,
            delete_token=delete_token,
            ip_hash=ip_hash
        )
        return Response(SnippetCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class SnippetCommentDeleteView(APIView):
    """Delete a comment using its delete token."""
    def delete(self, request, snippet_id, comment_id):
        comment = get_object_or_404(SnippetComment, id=comment_id, snippet_id=snippet_id)
        token = request.data.get('delete_token') or request.query_params.get('delete_token')
        if not token or token != comment.delete_token:
            return Response({'error': 'Invalid delete token'}, status=status.HTTP_403_FORBIDDEN)
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnippetReactionView(APIView):
    """Add/list reactions for a snippet."""
    def get(self, request, snippet_id):
        snippet = get_object_or_404(Snippet, id=snippet_id)
        if snippet.is_expired:
            return Response({'error': 'Snippet has expired'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'reactions': reaction_summary(snippet)})

    def post(self, request, snippet_id):
        snippet = get_object_or_404(Snippet, id=snippet_id)
        if snippet.is_expired:
            return Response({'error': 'Snippet has expired'}, status=status.HTTP_404_NOT_FOUND)
        ip_address = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()

        if rate_limit_exceeded(f"reaction_rate:{ip_hash}", limit=10, window_seconds=60):
            return Response({'error': 'Too many reactions, slow down.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = ReactionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reaction_type = serializer.validated_data['reaction_type']
        reaction, created = SnippetReaction.objects.get_or_create(snippet=snippet, reaction_type=reaction_type, defaults={'count': 0})
        if created:
            reaction.count = 1
            reaction.save(update_fields=['count'])
        else:
            SnippetReaction.objects.filter(id=reaction.id).update(count=models.F('count') + 1)
            reaction.refresh_from_db(fields=['count'])

        return Response({'reactions': reaction_summary(snippet)}, status=status.HTTP_201_CREATED)


class SnippetDiffQueryView(APIView):
    """Diff between versions using version numbers (latest vs prior by default)."""
    def get(self, request, snippet_id):
        snippet = get_object_or_404(Snippet, id=snippet_id)
        versions_qs = snippet.get_all_versions()
        if not versions_qs.exists():
            return Response({'error': 'No versions found'}, status=status.HTTP_404_NOT_FOUND)

        to_version_param = request.query_params.get('to')
        from_version_param = request.query_params.get('from')

        def pick_version(version_number, fallback):
            if version_number is None:
                return fallback
            return versions_qs.filter(version=version_number).first()

        latest = versions_qs.order_by('-version').first()
        try:
            target_version = pick_version(int(to_version_param) if to_version_param else None, latest)
        except ValueError:
            return Response({'error': 'Invalid to version'}, status=status.HTTP_400_BAD_REQUEST)
        if not target_version:
            return Response({'error': 'Target version not found'}, status=status.HTTP_404_NOT_FOUND)

        previous_version_number = target_version.version - 1
        try:
            source_version = pick_version(int(from_version_param) if from_version_param else previous_version_number, None)
        except ValueError:
            return Response({'error': 'Invalid from version'}, status=status.HTTP_400_BAD_REQUEST)

        if not source_version:
            return Response({'error': 'Source version not found'}, status=status.HTTP_404_NOT_FOUND)

        source_lines = source_version.content.splitlines()
        target_lines = target_version.content.splitlines()
        diff_generator = difflib.unified_diff(
            source_lines,
            target_lines,
            fromfile=f'v{source_version.version}',
            tofile=f'v{target_version.version}',
            lineterm=''
        )
        diff_text = '\n'.join(diff_generator)

        additions = sum(1 for line in diff_text.splitlines() if line.startswith('+') and not line.startswith('+++'))
        deletions = sum(1 for line in diff_text.splitlines() if line.startswith('-') and not line.startswith('---'))

        versions_meta = [
            {
                'id': str(v.id),
                'version': v.version,
                'created_at': v.created_at,
                'size': len(v.content),
                'lines': len(v.content.splitlines()),
            }
            for v in versions_qs
        ]

        return Response({
            'from_version': source_version.version,
            'to_version': target_version.version,
            'diff': diff_text,
            'additions': additions,
            'deletions': deletions,
            'versions': versions_meta,
        })
