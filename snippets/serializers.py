from rest_framework import serializers
from django.db import models
from .models import Snippet, SnippetView, SnippetDiff

class SnippetSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        required=False, 
        allow_blank=True,
        help_text="Optional password to protect access to the snippet"
    )
    expiration_minutes = serializers.ChoiceField(
        choices=Snippet.EXPIRATION_CHOICES,
        required=False,
        default=1440,  # 24 hours default
        help_text="Snippet expiration time in minutes"
    )
    encrypt_content = serializers.BooleanField(
        required=False, 
        default=False,
        help_text="Whether to encrypt the snippet content"
    )
    parent_id = serializers.UUIDField(
        required=False, 
        write_only=True,
        help_text="Parent snippet ID for creating versions"
    )

    class Meta:
        model = Snippet
        fields = [
            'id', 'content', 'language', 'created_at', 'expires_at', 
            'view_count', 'one_time_view', 'password', 'encrypt_content',
            'expiration_minutes', 'is_encrypted', 'parent_id', 'version'
        ]
        read_only_fields = ['id', 'created_at', 'view_count', 'expires_at', 'version']

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("Content cannot be empty")
        return value

    def validate_language(self, value):
        allowed_languages = [
            # Common web languages
            'javascript', 'typescript', 'html', 'css', 'php',
            # Backend languages
            'python', 'java', 'ruby', 'go', 'rust', 'c', 'cpp', 'csharp',
            # Data and config languages
            'json', 'yaml', 'xml', 'sql', 'markdown',
            # Shell scripting
            'bash', 'powershell', 'shell',
            # Mobile
            'swift', 'kotlin', 'objectivec',
            # Other languages
            'perl', 'haskell', 'scala', 'lua', 'r', 'dart', 'elixir', 'clojure',
            # Misc formats
            'diff', 'plaintext', 'dockerfile'
        ]
        if value not in allowed_languages:
            raise serializers.ValidationError(f"Language must be one of: {', '.join(allowed_languages)}")
        return value

    def create(self, validated_data):
        # Extract non-model fields
        password = validated_data.pop('password', None)
        expiration_minutes = int(validated_data.pop('expiration_minutes', 1440))
        encrypt_content = validated_data.pop('encrypt_content', False)
        parent_id = validated_data.pop('parent_id', None)
        
        # Set expiration time
        # validated_data['expires_at'] = serializers.DateTimeField().to_representation(
        #     serializers.DateTimeField().to_internal_value(
        #         serializers.DateTimeField().to_representation(
        #             serializers.DateTimeField().to_internal_value('') + 
        #             serializers.DurationField().to_internal_value(f'PT{expiration_minutes}M')
        #         )
        #     )
        # )
        
        # Check if this is a new version of an existing snippet
        if parent_id:
            try:
                parent_snippet = Snippet.objects.get(id=parent_id)
                snippet = Snippet(
                    content=validated_data['content'],
                    language=validated_data.get('language', parent_snippet.language),
                    one_time_view=validated_data.get('one_time_view', False),
                    parent_snippet=parent_snippet
                )
                # Determine the next version number
                highest_version = Snippet.objects.filter(
                    models.Q(id=parent_id) | models.Q(parent_snippet=parent_id)
                ).order_by('-version').values_list('version', flat=True).first() or 0
                snippet.version = highest_version + 1
                snippet.save()
            except Snippet.DoesNotExist:
                # If parent doesn't exist, create a new snippet
                snippet = Snippet.objects.create(**validated_data)
        else:
            # Create a new snippet
            snippet = Snippet.objects.create(**validated_data)
        
        # Set password if provided
        if password:
            snippet.set_password(password)
            snippet.save(update_fields=['password_hash', 'password_salt'])
        
        # Encrypt content if requested
        if encrypt_content:
            snippet.encrypt_content(password)
            snippet.save(update_fields=['content', 'is_encrypted'])
        
        return snippet


class SnippetViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetView
        fields = ['id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent']
        read_only_fields = ['id', 'viewed_at']


class SnippetDiffSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetDiff
        fields = ['id', 'source_snippet', 'target_snippet', 'diff_content', 'created_at']
        read_only_fields = ['id', 'created_at']


class SnippetPasswordCheckSerializer(serializers.Serializer):
    password = serializers.CharField(required=True)


class SnippetVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Snippet
        fields = ['id', 'version', 'created_at', 'language']
        read_only_fields = ['id', 'version', 'created_at', 'language']