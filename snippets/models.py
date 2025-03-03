# models.py
import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
import secrets
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings
import base64

class Snippet(models.Model):
    EXPIRATION_CHOICES = [
        (5, '5 minutes'),
        (60, '1 hour'),
        (360, '6 hours'),
        (1440, '24 hours'),
        (10080, '1 week'),
        (43200, '30 days'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.TextField()
    language = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    view_count = models.IntegerField(default=0)
    access_token = models.CharField(max_length=100, unique=True)
    is_encrypted = models.BooleanField(default=False)
    one_time_view = models.BooleanField(default=False)
    password_hash = models.CharField(max_length=128, null=True, blank=True)
    password_salt = models.CharField(max_length=64, null=True, blank=True)
    parent_snippet = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='versions')
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'snippets'
        indexes = [
            models.Index(fields=['access_token']),
            models.Index(fields=['expires_at']),
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
            
        hash_to_check = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            self.password_salt.encode('utf-8'), 
            100000
        ).hex()
        
        return hash_to_check == self.password_hash

    def encrypt_content(self, password=None):
        """Encrypt the snippet content"""
        if not self.is_encrypted:
            # Use password if provided, otherwise use default encryption key
            if password:
                # Derive a key from the password
                salt = secrets.token_bytes(16)
                kdf_key = hashlib.pbkdf2_hmac(
                    'sha256', 
                    password.encode('utf-8'), 
                    salt, 
                    100000
                )
                key = base64.urlsafe_b64encode(kdf_key)
                # Store salt for later decryption
                self.password_salt = salt.hex()
            else:
                # Use the application's encryption key
                key = settings.ENCRYPTION_KEY.encode()
                
            cipher = Fernet(key)
            encrypted_content = cipher.encrypt(self.content.encode('utf-8'))
            self.content = encrypted_content.decode('utf-8')
            self.is_encrypted = True
            return True
        return False

    def decrypt_content(self, password=None):
        """Decrypt the snippet content"""
        if self.is_encrypted:
            try:
                if password and self.password_salt:
                    # Derive the key from the password
                    salt = bytes.fromhex(self.password_salt)
                    kdf_key = hashlib.pbkdf2_hmac(
                        'sha256', 
                        password.encode('utf-8'), 
                        salt, 
                        100000
                    )
                    key = base64.urlsafe_b64encode(kdf_key)
                else:
                    # Use the application's encryption key
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

class SnippetView(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snippet = models.ForeignKey(Snippet, on_delete=models.CASCADE, related_name='views')
    viewed_at = models.DateTimeField(auto_now_add=True)
    ip_hash = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=255)

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