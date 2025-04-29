from rest_framework import serializers
from .models import Snippet, SnippetView
from django.utils import timezone
from datetime import timedelta

class SnippetSerializer(serializers.ModelSerializer):
    expiration = serializers.CharField(required=False, write_only=True)
    class Meta:
        model = Snippet
        fields = ['id', 'content', 'language', 'created_at', 'expires_at', 
                 'view_count', 'one_time_view', 'expiration']
        read_only_fields = ['id', 'created_at', 'view_count', 'expires_at']

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("Content cannot be empty")
        return value

    def validate_language(self, value):
        allowed_languages = [
            'javascript', 'python', 'typescript', 'java', 'cpp', 'php', 'rust', 'sql', 
            'html', 'css', 'markdown', 'json', 'swift', 'go', 'ruby', 'kotlin', 'scala', 
            'csharp', 'fsharp', 'dart', 'lua', 'perl', 'r', 'shell', 'powershell', 
            'yaml', 'toml', 'graphql', 'haskell', 'ocaml', 'elixir', 'text'
        ]
        if value not in allowed_languages:
            raise serializers.ValidationError(f"Language must be one of: {', '.join(allowed_languages)}")
        return value

    def create(self, validated_data):
        # Extract expiration if provided
        expiration = validated_data.pop('expiration', '24h')  # Default to 24h
        
        # Create the snippet without setting expires_at yet
        snippet = Snippet(**validated_data)
        
        # Convert expiration string to an actual datetime
        now = timezone.now()
        if expiration == '1h':
            snippet.expires_at = now + timedelta(hours=1)
        elif expiration == '24h':
            snippet.expires_at = now + timedelta(hours=24)
        elif expiration == '7d':
            snippet.expires_at = now + timedelta(days=7)
        else:
            # Default to 24 hours if invalid format
            snippet.expires_at = now + timedelta(hours=24)
        
        snippet.save()
        return snippet

class SnippetViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetView
        fields = ['id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent']
        read_only_fields = ['id', 'viewed_at']