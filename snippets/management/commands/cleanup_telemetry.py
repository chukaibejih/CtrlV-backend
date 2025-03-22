# snippets/management/commands/cleanup_telemetry.py

import os
import gzip
import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from snippets.models import VSCodeTelemetryEvent


class Command(BaseCommand):
    help = 'Clean up old telemetry data with optional archiving'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete telemetry events older than this many days (default: 90)'
        )
        parser.add_argument(
            '--archive',
            action='store_true',
            help='Archive data before deletion'
        )
        parser.add_argument(
            '--archive-dir',
            type=str,
            default='telemetry_archives',
            help='Directory to store archives (default: telemetry_archives)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Batch size for deletion to avoid memory issues (default: 1000)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        archive = options['archive']
        archive_dir = options['archive_dir']
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        
        # Calculate cutoff date
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Get count of records to be deleted
        count = VSCodeTelemetryEvent.objects.filter(timestamp__lt=cutoff_date).count()
        
        if count == 0:
            self.stdout.write("No telemetry records to clean up.")
            return
        
        self.stdout.write(f"Found {count} telemetry records older than {days} days.")
        
        if dry_run:
            self.stdout.write("Dry run complete. No records deleted.")
            return
        
        # Create archive directory if needed
        if archive and not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
        
        # Process in batches to avoid memory issues
        processed = 0
        
        while processed < count:
            # Get batch of records
            batch = VSCodeTelemetryEvent.objects.filter(
                timestamp__lt=cutoff_date
            ).order_by('timestamp')[:batch_size]
            
            # Archive if requested
            if archive:
                self._archive_batch(batch, archive_dir)
            
            # Get IDs for deletion
            ids_to_delete = [record.id for record in batch]
            
            # Delete batch
            with transaction.atomic():
                deletion_count = VSCodeTelemetryEvent.objects.filter(
                    id__in=ids_to_delete
                ).delete()[0]
                
                processed += deletion_count
                self.stdout.write(f"Deleted {deletion_count} records (total {processed}/{count})")
        
        self.stdout.write(self.style.SUCCESS(f"Successfully cleaned up {processed} telemetry records."))
    
    def _archive_batch(self, batch, archive_dir):
        """Archive a batch of telemetry records"""
        # Create archive filename with date range
        if not batch:
            return
            
        min_date = min(record.timestamp for record in batch).strftime('%Y%m%d')
        max_date = max(record.timestamp for record in batch).strftime('%Y%m%d')
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{archive_dir}/telemetry_{min_date}_to_{max_date}_{timestamp}.json.gz"
        
        # Convert records to JSON
        records = []
        for record in batch:
            data = {
                'id': str(record.id),
                'event_type': record.event_type,
                'event_name': record.event_name,
                'client_id': record.client_id,
                'timestamp': record.timestamp.isoformat(),
                'vs_code_version': record.vs_code_version,
                'language': record.language,
                'code_length': record.code_length,
                'error_message': record.error_message,
                'request_data': record.request_data
            }
            records.append(data)
        
        # Write compressed JSON file
        with gzip.open(filename, 'wt', encoding='utf-8') as f:
            json.dump(records, f)
        
        self.stdout.write(f"Archived {len(records)} records to {filename}")