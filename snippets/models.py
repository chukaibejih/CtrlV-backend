
# models.py
import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
import secrets

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

    def increment_view_count(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])
    
    def get_sharing_url(self, base_url):
        return f"{base_url}/s/{self.id}?token={self.access_token}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

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