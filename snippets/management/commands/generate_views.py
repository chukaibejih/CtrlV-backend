"""
Django shell script to generate 2031 realistic view records for snippets.
Run this in Django shell: python manage.py shell < generate_views.py

This script creates synthetic views to improve engagement metrics and populate analytics data.
"""

import random
import hashlib
import uuid
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction, connection
from django.db import models
from snippets.models import Snippet, SnippetView, SnippetMetrics

print("Starting view generation for 2031 views...")

def get_snippet_candidates():
    """Get snippets that are good candidates for view generation"""
    return list(
        Snippet.objects.select_related()
        .order_by('created_at')
        .values(
            'id', 'created_at', 'expires_at', 'language', 
            'view_count', 'is_encrypted', 'one_time_view'
        )
    )

def select_weighted_snippet(snippets, language_weights):
    """Select a snippet with weighted probability based on language and recency"""
    if not snippets:
        return None
        
    # Calculate weights for each snippet
    snippet_weights = []
    
    for snippet in snippets:
        weight = 1.0
        
        # Language weight
        lang_weight = language_weights.get(snippet['language'], 0.02)
        weight *= lang_weight
        
        # Recency weight (newer snippets more likely to be viewed)
        days_old = (timezone.now() - snippet['created_at']).days
        recency_weight = max(0.1, 1.0 - (days_old / 30.0))  # Decay over 30 days
        weight *= recency_weight
        
        # Reduce weight for already highly viewed snippets
        if snippet['view_count'] > 10:
            weight *= 0.3
        elif snippet['view_count'] > 5:
            weight *= 0.7
        
        # Boost for encrypted/interesting content
        if snippet['is_encrypted']:
            weight *= 1.2
            
        snippet_weights.append(weight)
    
    # Weighted random selection
    if not snippet_weights or sum(snippet_weights) == 0:
        return random.choice(snippets)
        
    return random.choices(snippets, weights=snippet_weights, k=1)[0]

def generate_view_timestamp(created_at, expires_at, hour_weights):
    """Generate a realistic timestamp between creation and expiration"""
    # Ensure we're working with timezone-aware datetimes
    if timezone.is_naive(created_at):
        created_at = timezone.make_aware(created_at)
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at)
        
    # Calculate the valid time window
    total_seconds = (expires_at - created_at).total_seconds()
    
    if total_seconds <= 0:
        return None
    
    # Most views happen in the first 25% of snippet lifetime
    # Some views happen throughout the lifetime
    lifecycle_position = random.choices(
        [0.25, 1.0],  # First quarter vs full lifetime
        weights=[0.7, 0.3],  # 70% in first quarter
        k=1
    )[0]
    
    # Random time within the selected portion
    max_offset = total_seconds * lifecycle_position
    time_offset = random.uniform(0, max_offset)
    
    base_time = created_at + timedelta(seconds=time_offset)
    
    # Adjust to a weighted hour
    target_hour = random.choices(
        list(hour_weights.keys()),
        weights=list(hour_weights.values()),
        k=1
    )[0]
    
    # Set to target hour with some minute randomization
    adjusted_time = base_time.replace(
        hour=target_hour,
        minute=random.randint(0, 59),
        second=random.randint(0, 59)
    )
    
    # Ensure we don't go outside the valid window
    if adjusted_time < created_at:
        adjusted_time = created_at + timedelta(minutes=random.randint(1, 60))
    elif adjusted_time > expires_at:
        adjusted_time = expires_at - timedelta(minutes=random.randint(1, 60))
        
    return adjusted_time

def generate_simple_ip_hash():
    """Generate a simple IP hash without complex simulation"""
    # Simple hash generation for consistency
    fake_ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    return hashlib.sha256(fake_ip.encode()).hexdigest()

def get_simple_user_agent():
    """Get a simple user agent string"""
    agents = [
        'Mozilla/5.0 (Chrome)',
        'Mozilla/5.0 (Firefox)', 
        'Mozilla/5.0 (Safari)',
        'Mozilla/5.0 (Edge)'
    ]
    return random.choice(agents)

def create_views_batch(views_data):
    """Create view records in batch for performance with proper backdating"""
    with transaction.atomic():
        # Use raw SQL to bypass auto_now_add behavior and properly backdate records
        with connection.cursor() as cursor:
            # Prepare batch insert query
            insert_query = """
                INSERT INTO snippet_views (id, snippet_id, viewed_at, ip_hash, user_agent, location)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            
            # Prepare batch data
            batch_data = []
            for view in views_data:
                batch_data.append([
                    str(uuid.uuid4()),  # Generate UUID for id
                    str(view['snippet_id']),
                    view['viewed_at'],
                    view['ip_hash'],
                    view['user_agent'],
                    view['location']
                ])
            
            # Execute batch insert
            cursor.executemany(insert_query, batch_data)

def update_snippet_view_counts(views_data):
    """Update view counts for affected snippets"""
    # Count views per snippet
    snippet_view_counts = {}
    for view in views_data:
        snippet_id = view['snippet_id']
        snippet_view_counts[snippet_id] = snippet_view_counts.get(snippet_id, 0) + 1
    
    # Update in batches
    with transaction.atomic():
        for snippet_id, count in snippet_view_counts.items():
            Snippet.objects.filter(id=snippet_id).update(
                view_count=models.F('view_count') + count
            )

def update_daily_metrics(views_data):
    """Update daily metrics based on generated views"""
    # Group views by date
    daily_counts = {}
    for view in views_data:
        date = view['viewed_at'].date()
        daily_counts[date] = daily_counts.get(date, 0) + 1
    
    # Update metrics for each date
    with transaction.atomic():
        for date, count in daily_counts.items():
            metrics, created = SnippetMetrics.objects.get_or_create(
                date=date,
                defaults={'total_views': 0, 'total_snippets': 0}
            )
            metrics.total_views += count
            metrics.save(update_fields=['total_views'])

# Main execution
try:
    # Configuration
    TARGET_VIEWS = 2031
    BATCH_SIZE = 500
    
    # Get all snippets for analysis
    snippets = get_snippet_candidates()
    
    if not snippets:
        print("ERROR: No suitable snippets found for view generation")
        exit()
    
    print(f"Found {len(snippets)} snippets eligible for view generation")
    
    # Language popularity weights (based on your data)
    language_weights = {
        'javascript': 0.64,  # 562/876
        'text': 0.11,        # 10/876 + boost for readability
        'python': 0.08,      # 3/876 + boost for popularity
        'typescript': 0.06,  # 2/876 + boost
        'json': 0.06,        # 1/876 + boost
        'go': 0.05,          # 1/876 + boost
    }
    
    # Peak hours based on your analytics (12, 8, 2, 7, 10)
    peak_hours = [2, 7, 8, 10, 12]
    hour_weights = {}
    for hour in range(24):
        if hour in peak_hours:
            hour_weights[hour] = 3.0  # 3x more likely during peak
        elif 6 <= hour <= 22:  # Business/active hours
            hour_weights[hour] = 1.5
        else:  # Night hours
            hour_weights[hour] = 0.3
    
    # Generate views in batches
    total_views_created = 0
    
    for batch_start in range(0, TARGET_VIEWS, BATCH_SIZE):
        batch_size = min(BATCH_SIZE, TARGET_VIEWS - total_views_created)
        batch_views = []
        
        print(f"Generating batch {batch_start//BATCH_SIZE + 1}...")
        
        for _ in range(batch_size):
            # Select snippet with weighted probability
            snippet = select_weighted_snippet(snippets, language_weights)
            if not snippet:
                continue
                
            # Generate realistic view timestamp within snippet lifetime
            view_time = generate_view_timestamp(
                snippet['created_at'], 
                snippet['expires_at'],
                hour_weights
            )
            
            if not view_time:
                continue
            
            # Create view record
            view = {
                'snippet_id': snippet['id'],
                'viewed_at': view_time,
                'ip_hash': generate_simple_ip_hash(),
                'user_agent': get_simple_user_agent(),
                'location': None  # Keep simple
            }
            
            batch_views.append(view)
        
        if batch_views:
            # Create the views
            create_views_batch(batch_views)
            # Update snippet view counts
            update_snippet_view_counts(batch_views)
            # Update daily metrics
            update_daily_metrics(batch_views)
            
            total_views_created += len(batch_views)
            print(f"  Created {len(batch_views)} views (Total: {total_views_created})")
        
        if total_views_created >= TARGET_VIEWS:
            break
    
    print(f"\n✅ SUCCESS: Created {total_views_created} view records")
    print(f"📊 This should significantly improve your engagement metrics!")
    
except Exception as e:
    print(f"❌ ERROR: {str(e)}")
    import traceback
    traceback.print_exc()

print("View generation complete.")