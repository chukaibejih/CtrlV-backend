from rest_framework import serializers
from .models import Snippet, SnippetView

class SnippetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Snippet
        fields = ['id', 'content', 'language', 'created_at', 'expires_at', 
                 'view_count', 'one_time_view']
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

class SnippetViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetView
        fields = ['id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent']
        read_only_fields = ['id', 'viewed_at']