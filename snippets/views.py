from datetime import timedelta
import hashlib
import difflib
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import models
from django.shortcuts import get_object_or_404
from .models import Snippet, SnippetMetrics, SnippetView, SnippetDiff
from .serializers import (
    SnippetSerializer, SnippetViewSerializer, SnippetDiffSerializer,
    SnippetPasswordCheckSerializer, SnippetVersionSerializer
)

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
                'sharing_url': snippet.get_sharing_url(request.build_absolute_uri('/')[:-1]),
                'expires_at': snippet.expires_at,
                'version': snippet.version
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
        
        # If the snippet is password-protected, verify password first
        if snippet.password_hash and not request.query_params.get('verified'):
            return Response(
                {'requires_password': True},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # If the snippet is encrypted, note it in the response
        needs_decryption = snippet.is_encrypted
        
        # Record the view
        ip_address = request.META.get('REMOTE_ADDR', '')
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        SnippetView.objects.create(
            snippet=snippet,
            ip_hash=ip_hash,
            user_agent=user_agent
        )
        
        snippet.increment_view_count()

        # Update metrics
        SnippetMetrics.record_snippet_view()

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
            
        # Add decryption requirement flag if necessary
        if needs_decryption:
            response_data['needs_decryption'] = True
            
        return Response(response_data)

    # To handle password verification
    def post(self, request, snippet_id):
        print("request.data: ", request.data)
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
                # If the snippet is encrypted, decrypt it with the password
                if snippet.is_encrypted:
                    success = snippet.decrypt_content(password)
                    if not success:
                        return Response(
                            {'error': 'Invalid password for decryption'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                
                return Response({'verified': True})
            else:
                return Response(
                    {'error': 'Invalid password'},
                    status=status.HTTP_403_FORBIDDEN
                )
                
        elif action == 'decrypt':
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
                success = snippet.decrypt_content(password)
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
        
        serializer = SnippetSerializer(data=request_data)
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