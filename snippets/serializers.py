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
    expiration = serializers.CharField(
        write_only=True,
        required=False,
        default="24h",
        help_text="Expiration time: 1h, 24h, 7d, 30d"
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
    max_views = serializers.IntegerField(
        required=False,
        min_value=1,
        allow_null=True,
        help_text="Maximum allowed views before burn-after-read triggers"
    )
    
    is_public = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether this snippet should appear in the public feed"
    )
    public_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="Display name for public feed (required if is_public=True)"
    )
    protection_level = serializers.ReadOnlyField()
    remaining_views = serializers.SerializerMethodField()

    class Meta:
        model = Snippet
        fields = [
            'id', 'content', 'language', 'created_at', 'expires_at', 'expiration',
            'view_count', 'one_time_view', 'password', 'encrypt_content',
            'is_encrypted', 'parent_id', 'version', 'is_public', 'public_name',
            'protection_level', 'max_views', 'remaining_views', 'allow_comments'
        ]
        read_only_fields = ['id', 'created_at', 'view_count', 'expires_at', 'version', 'is_encrypted', 'protection_level', 'remaining_views']

    def validate(self, attrs):
        # If password is provided, automatically set encrypt_content to True
        if attrs.get('password'):
            attrs['encrypt_content'] = True
            
        # If encrypt_content is True, require a password
        if attrs.get('encrypt_content') and not attrs.get('password'):
            raise serializers.ValidationError({
                'password': 'A password is required when encrypting content.'
            })
        
        is_public = attrs.get('is_public', False)
        public_name = attrs.get('public_name', '').strip()
        one_time_view = attrs.get('one_time_view', False)
        password = attrs.get('password', '').strip()
        max_views = attrs.get('max_views')
        expiration_input = attrs.get('expiration', '24h')
        
        # Public snippets must have a name
        if is_public and not public_name:
            raise serializers.ValidationError({
                'public_name': 'A public name is required for public snippets.'
            })
        
        # Public one-time snippets must be password protected
        if is_public and one_time_view and not password:
            raise serializers.ValidationError({
                'password': 'Public one-time view snippets must be password protected.'
            })

        # Cap view limits for safety
        if max_views is not None:
            if max_views < 1:
                raise serializers.ValidationError({'max_views': 'Max views must be at least 1.'})
            if max_views > 1000:
                raise serializers.ValidationError({'max_views': 'Max views capped at 1000 to prevent abuse.'})

        # Normalize expiration now so errors surface during validation
        attrs['expires_at'] = self._calculate_expiration(expiration_input)
            
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
        expiration = validated_data.pop('expiration', '24h')
        max_views = validated_data.get('max_views')
        
        # expires_at already set in validate
        
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
                    is_public=validated_data.get('is_public', False),
                    public_name=validated_data.get('public_name'),
                    parent_snippet=parent_snippet,
                    max_views=max_views,
                    allow_comments=validated_data.get('allow_comments', True),
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
    
    def _calculate_expiration(self, expiration_str):
        """Convert expiration string to datetime"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        
        presets = {
            '10m': now + timedelta(minutes=10),
            '1h': now + timedelta(hours=1),
            '24h': now + timedelta(hours=24),
            '48h': now + timedelta(hours=48),
            '7d': now + timedelta(days=7),
            '30d': now + timedelta(days=30),
        }

        if expiration_str in presets:
            return presets[expiration_str]

        if isinstance(expiration_str, str):
            # Try ISO 8601 timestamp
            try:
                parsed = timezone.datetime.fromisoformat(expiration_str.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed <= now:
                    raise serializers.ValidationError('Expiration must be in the future.')
                # Cap at 90 days to avoid unbounded retention
                if parsed > now + timedelta(days=90):
                    raise serializers.ValidationError('Expiration cannot exceed 90 days.')
                return parsed
            except ValueError:
                pass

        raise serializers.ValidationError('Invalid expiration format. Use 10m,1h,24h,48h,7d,30d or ISO-8601 timestamp.')

    def get_remaining_views(self, obj):
        return obj.remaining_views


class PublicSnippetSerializer(serializers.ModelSerializer):
    """Serializer for public feed - limited fields for privacy"""
    protection_level = serializers.ReadOnlyField()
    
    class Meta:
        model = Snippet
        fields = [
            'id', 'public_name', 'language', 'created_at', 
            'protection_level', 'access_token'
        ]
        read_only_fields = fields
        

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


class SnippetCommentSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    content = serializers.CharField()
    display_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    created_at = serializers.DateTimeField(read_only=True)
    delete_token = serializers.CharField(read_only=True)

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("Content cannot be empty.")
        if len(value) > 2000:
            raise serializers.ValidationError("Content too long (max 2000 characters).")
        return value


class ReactionRequestSerializer(serializers.Serializer):
    reaction_type = serializers.CharField()

    def validate_reaction_type(self, value):
        allowed = {'like', 'insight', 'question'}
        if value not in allowed:
            raise serializers.ValidationError(f"Reaction type must be one of {', '.join(sorted(allowed))}.")
        return value
