# models.py
import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
import secrets
import hashlib
from django.db import transaction
from django.core.cache import cache
from cryptography.fernet import Fernet
from django.conf import settings
import base64

class Snippet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.TextField()
    language = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    view_count = models.IntegerField(default=0)
    access_token = models.CharField(max_length=100, unique=True)
    is_encrypted = models.BooleanField(default=False)
    one_time_view = models.BooleanField(default=False)
    # Password protection fields
    password_hash = models.CharField(max_length=128, null=True, blank=True)
    password_salt = models.CharField(max_length=128, null=True, blank=True)
    # Versioning fields
    parent_snippet = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='versions')
    version = models.PositiveIntegerField(default=1)
    is_consumed = models.BooleanField(default=False) 
    consumed_at = models.DateTimeField(null=True, blank=True)
    # IP tracking
    creator_ip_hash = models.CharField(max_length=128, null=True, blank=True)
    creator_location = models.CharField(max_length=255, null=True, blank=True)
    is_public = models.BooleanField(default=False)
    public_name = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = 'snippets'
        indexes = [
            models.Index(fields=['access_token']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['is_public', 'expires_at', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Default expiration time is 24 hours
            self.expires_at = timezone.now() + timedelta(hours=24)
        if not self.access_token:
            # Generate a secure random token
            self.access_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def set_password(self, password):
        """Hash password and store it"""
        if password:
            # Generate a random salt
            salt = secrets.token_hex(16)
            # Create a hash of the password with the salt
            password_hash = hashlib.pbkdf2_hmac(
                'sha256', 
                password.encode('utf-8'), 
                salt.encode('utf-8'), 
                100000  # Number of iterations
            ).hex()
            
            self.password_salt = salt
            self.password_hash = password_hash
            return True
        return False

    def check_password(self, password):
        """Verify a password against the stored hash"""
        if not self.password_hash or not self.password_salt:
            return True  # No password set
        
        # Convert memoryview to bytes if needed
        salt = self.password_salt
        if isinstance(salt, memoryview):
            salt = bytes(salt)
        elif isinstance(salt, str):
            salt = salt.encode('utf-8')
        
        hash_to_check = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            salt,  # Now using the properly formatted salt
            100000
        ).hex()
        
        return hash_to_check == self.password_hash

    def encrypt_content(self):
        """Encrypt the snippet content"""
        if not self.is_encrypted:
            key = settings.ENCRYPTION_KEY.encode()
                
            cipher = Fernet(key)
            encrypted_content = cipher.encrypt(self.content.encode('utf-8'))
            self.content = encrypted_content.decode('utf-8')
            self.is_encrypted = True
            return True
        return False

    def decrypt_content(self):
        """Decrypt the snippet content"""
        if self.is_encrypted:
            try:
                key = settings.ENCRYPTION_KEY.encode()
                    
                cipher = Fernet(key)
                decrypted_content = cipher.decrypt(self.content.encode('utf-8'))
                self.content = decrypted_content.decode('utf-8')
                self.is_encrypted = False
                return True
            except Exception:
                return False
        return True  # Already decrypted

    def increment_view_count(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])
    
    def get_sharing_url(self, base_url):
        return f"{base_url}/s/{self.id}?token={self.access_token}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    @property
    def is_available(self):
        """Check if snippet is available for viewing"""
        if self.is_expired:
            return False
        if self.one_time_view and self.is_consumed:
            return False
        return True
    
    def mark_as_consumed(self):
        """Mark snippet as consumed for one-time view"""
        if self.one_time_view:
            self.is_consumed = True
            self.consumed_at = timezone.now()
            self.save(update_fields=['is_consumed', 'consumed_at'])
    
    @property
    def protection_level(self):
        """
        Returns protection level for public feed display
        Returns: 'none', 'password', or 'password_onetime'
        """
        if not self.password_hash:
            return 'none'
        elif self.one_time_view:
            return 'password_onetime'
        else:
            return 'password'
    
    def clean(self):
        """Custom validation for public snippets"""
        from django.core.exceptions import ValidationError
        
        # If public and one_time_view, must have password
        if self.is_public and self.one_time_view and not self.password_hash:
            raise ValidationError(
                "Public one-time view snippets must be password protected"
            )
        
        # If public, must have public_name
        if self.is_public and not self.public_name:
            raise ValidationError(
                "Public snippets must have a public name"
            )

    def create_new_version(self, content, language=None):
        """Create a new version of this snippet"""
        # Get the highest version number among related versions
        highest_version = Snippet.objects.filter(
            models.Q(id=self.id) | models.Q(parent_snippet=self) | models.Q(parent_snippet=self.parent_snippet)
        ).order_by('-version').values_list('version', flat=True).first() or 0
        
        # Create new version
        new_snippet = Snippet(
            content=content,
            language=language or self.language,
            parent_snippet=self.parent_snippet or self,  # Link to original parent or self if this is the original
            version=highest_version + 1
        )
        new_snippet.save()
        return new_snippet

    def get_all_versions(self):
        """Get all versions of this snippet in order"""
        if self.parent_snippet:
            # This is a child version, get all siblings including parent
            return Snippet.objects.filter(
                models.Q(id=self.parent_snippet.id) | 
                models.Q(parent_snippet=self.parent_snippet)
            ).order_by('version')
        else:
            # This is a parent, get all children
            return Snippet.objects.filter(
                models.Q(id=self.id) | 
                models.Q(parent_snippet=self)
            ).order_by('version')

    @classmethod
    def record_snippet_creation(cls):
        # Use cache to reduce database hits
        cache_key = f'snippet_metrics_{timezone.now().date()}'
        
        # Increment in cache first
        current_count = cache.get(cache_key, 0) + 1
        cache.set(cache_key, current_count, 3600)  # Cache for 1 hour
        
        # Batch update to reduce database writes
        if current_count % 10 == 0:
            with transaction.atomic():
                today = timezone.now().date()
                obj, created = SnippetMetrics.objects.get_or_create(date=today)
                obj.total_snippets += current_count
                obj.save(update_fields=['total_snippets'])
                
                # Reset cache after database update
                cache.delete(cache_key)

class SnippetView(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snippet = models.ForeignKey(Snippet, on_delete=models.CASCADE, related_name='views')
    viewed_at = models.DateTimeField(auto_now_add=True)
    ip_hash = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=255)
    location = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'snippet_views'
        indexes = [
            models.Index(fields=['snippet', 'viewed_at']),
        ]


class SnippetMetrics(models.Model):
    date = models.DateField(unique=True)  # Store metrics per day
    total_snippets = models.PositiveIntegerField(default=0)
    total_views = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "snippet_metrics"

    @classmethod
    def record_snippet_creation(cls):
        today = timezone.now().date()
        obj, created = cls.objects.get_or_create(date=today)
        obj.total_snippets += 1
        obj.save(update_fields=['total_snippets'])

    @classmethod
    def record_snippet_view(cls):
        today = timezone.now().date()
        obj, created = cls.objects.get_or_create(date=today)
        obj.total_views += 1
        obj.save(update_fields=['total_views'])


class SnippetDiff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_snippet = models.ForeignKey(Snippet, on_delete=models.CASCADE, related_name='source_diffs')
    target_snippet = models.ForeignKey(Snippet, on_delete=models.CASCADE, related_name='target_diffs')
    diff_content = models.TextField()  # Store the unified diff
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'snippet_diffs'
        unique_together = ('source_snippet', 'target_snippet')


class VSCodeExtensionMetrics(models.Model):
    date = models.DateField(unique=True)
    total_actions = models.PositiveIntegerField(default=0)
    selection_shares = models.PositiveIntegerField(default=0)
    file_shares = models.PositiveIntegerField(default=0)
    unique_clients = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    
    class Meta:
        db_table = "vscode_extension_metrics"
        
    @classmethod
    def record_action(cls, event_name, client_id, is_error=False):
        # Use cache to reduce database hits
        today = timezone.now().date()
        
        # Track total actions
        action_cache_key = f'vscode_actions_{today}'
        current_count = cache.get(action_cache_key, 0) + 1
        cache.set(action_cache_key, current_count, 3600)  # Cache for 1 hour
        
        # Track specific action type
        type_cache_key = None
        if event_name == 'shareSelectedCode':
            type_cache_key = f'vscode_selections_{today}'
        elif event_name == 'shareEntireFile':
            type_cache_key = f'vscode_files_{today}'
            
        if type_cache_key:
            type_count = cache.get(type_cache_key, 0) + 1
            cache.set(type_cache_key, type_count, 3600)
        
        # Track errors
        if is_error:
            error_cache_key = f'vscode_errors_{today}'
            error_count = cache.get(error_cache_key, 0) + 1
            cache.set(error_cache_key, error_count, 3600)
        
        # Track unique clients (using a set in cache)
        client_set_key = f'vscode_clients_{today}'
        client_set = cache.get(client_set_key, set())
        client_set.add(client_id)
        cache.set(client_set_key, client_set, 3600)
        
        # Batch update to database periodically
        if current_count % 10 == 0:
            with transaction.atomic():
                obj, created = cls.objects.get_or_create(date=today)
                
                # Update counts
                obj.total_actions += current_count
                
                if type_cache_key == f'vscode_selections_{today}':
                    obj.selection_shares += cache.get(type_cache_key, 0)
                    cache.delete(type_cache_key)
                
                if type_cache_key == f'vscode_files_{today}':
                    obj.file_shares += cache.get(type_cache_key, 0)
                    cache.delete(type_cache_key)
                
                if is_error:
                    obj.error_count += cache.get(error_cache_key, 0)
                    cache.delete(error_cache_key)
                
                # Update unique clients count
                obj.unique_clients = len(client_set)
                
                obj.save()
                
                # Reset cache after database update
                cache.delete(action_cache_key)
                

class VSCodeTelemetryEvent(models.Model):
    """Stores raw telemetry events from VSCode extension for detailed analysis"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=50)  # e.g., 'vscode_extension'
    event_name = models.CharField(max_length=50)  # e.g., 'shareSelectedCode', 'shareEntireFile', 'shareError'
    client_id = models.CharField(max_length=64, db_index=True)  # Anonymous client identifier
    timestamp = models.DateTimeField()
    vs_code_version = models.CharField(max_length=30, null=True, blank=True)
    language = models.CharField(max_length=30, null=True, blank=True)  # Language of code being shared
    code_length = models.PositiveIntegerField(null=True, blank=True)  # Length of code being shared
    error_message = models.TextField(null=True, blank=True)  # Error message if applicable
    request_data = models.JSONField(null=True, blank=True)  # Store the full request JSON

    class Meta:
        db_table = "vscode_telemetry_events"
        indexes = [
            models.Index(fields=['event_name', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
    
    @classmethod
    def create_from_request(cls, request_data):
        """Create a telemetry event record from the incoming request data"""
        try:
            timestamp = timezone.now()
            if 'timestamp' in request_data:
                try:
                    # Parse ISO timestamp from client
                    timestamp = timezone.datetime.fromisoformat(
                        request_data['timestamp'].replace('Z', '+00:00')
                    )
                except (ValueError, TypeError):
                    # If parsing fails, use current time
                    pass
                
            # Extract common fields
            event = cls(
                event_type=request_data.get('event_type', 'unknown'),
                event_name=request_data.get('event_name', 'unknown'),
                client_id=request_data.get('client_id', 'anonymous'),
                timestamp=timestamp,
                vs_code_version=request_data.get('vs_code_version'),
                language=request_data.get('language'),
                code_length=request_data.get('codeLength'),
                error_message=request_data.get('error'),
                request_data=request_data  # Store the full request data
            )
            event.save()
            return event
        except Exception as e:
            # Log error but don't fail - telemetry should be non-blocking
            print(f"Error saving telemetry event: {e}")
            return None