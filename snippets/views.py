from datetime import timedelta
import hashlib
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import models
from django.shortcuts import get_object_or_404
from .models import Snippet, SnippetView
from .serializers import SnippetSerializer, SnippetViewSerializer

class SnippetCreateView(APIView):
    def post(self, request):
        serializer = SnippetSerializer(data=request.data)
        if serializer.is_valid():
            snippet = serializer.save()
            
            # Return both ID and access token
            return Response({
                'id': snippet.id,
                'access_token': snippet.access_token,
                'sharing_url': snippet.get_sharing_url(request.build_absolute_uri('/')[:-1])
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SnippetRetrieveView(APIView):
    def get(self, request, snippet_id):
        # Get access token from query params
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

        # Check expiration
        if snippet.is_expired:
            return Response(
                {'error': 'Snippet has expired'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Handle one-time viewing
        if snippet.one_time_view and snippet.view_count > 0:
            return Response(
                {'error': 'This snippet has already been viewed'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        snippet.increment_view_count()
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