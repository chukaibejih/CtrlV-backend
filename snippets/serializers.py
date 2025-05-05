import hashlib
from rest_framework import serializers
from django.db import models
from .models import Snippet, SnippetView, SnippetDiff

class SnippetSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        required=False, 
        allow_blank=True,
        help_text="Password to protect and encrypt the snippet"
    )
    encrypt_content = serializers.BooleanField(
        write_only=True,
        required=False, 
        default=False,
        help_text="Whether to encrypt the snippet content (automatically true if password is provided)"
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
            'is_encrypted', 'parent_id', 'version'
        ]
        read_only_fields = ['id', 'created_at', 'view_count', 'expires_at', 'version', 'is_encrypted']

    def validate(self, attrs):
        # If password is provided, automatically set encrypt_content to True
        if attrs.get('password'):
            attrs['encrypt_content'] = True
            
        # If encrypt_content is True, require a password
        if attrs.get('encrypt_content') and not attrs.get('password'):
            raise serializers.ValidationError({
                'password': 'A password is required when encrypting content.'
            })
            
        return attrs

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
        # Extract non-model fields
        password = validated_data.pop('password', None)
        encrypt_content = validated_data.pop('encrypt_content', False)
        parent_id = validated_data.pop('parent_id', None)
        
        # Get creator IP information if available
        request = self.context.get('request')
        if request:
            ip_address = request.META.get('REMOTE_ADDR', '')
            validated_data['creator_ip_hash'] = hashlib.sha256(ip_address.encode()).hexdigest()
            # You could add IP geolocation here (using a service like MaxMind GeoIP)
            # validated_data['creator_location'] = get_location_from_ip(ip_address)
        
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
                # Add IP info
                if 'creator_ip_hash' in validated_data:
                    snippet.creator_ip_hash = validated_data['creator_ip_hash']
                if 'creator_location' in validated_data:
                    snippet.creator_location = validated_data['creator_location']
                    
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
        
        # Process password and encryption
        if password:
            # First set the password (generates auth salt/hash)
            snippet.set_password(password)
            snippet.encrypt_content()
            
            # Save all changes at once
            snippet.save()
        
        return snippet


class SnippetViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetView
        fields = ['id', 'snippet', 'viewed_at', 'ip_hash', 'user_agent', 'location']
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