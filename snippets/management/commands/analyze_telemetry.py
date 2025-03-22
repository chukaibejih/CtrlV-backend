# snippets/management/commands/analyze_telemetry.py

import csv
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Avg, Max, Min, Q
from snippets.models import VSCodeTelemetryEvent, VSCodeExtensionMetrics


class Command(BaseCommand):
    help = 'Analyze telemetry data from VSCode extension'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to analyze (default: 7)'
        )
        parser.add_argument(
            '--export',
            type=str,
            help='Export data to CSV file'
        )
        parser.add_argument(
            '--event-type',
            type=str,
            help='Filter by event type (e.g., shareSelectedCode)'
        )
        parser.add_argument(
            '--errors-only',
            action='store_true',
            help='Show only error events'
        )

    def handle(self, *args, **options):
        days = options['days']
        event_type = options.get('event_type')
        errors_only = options.get('errors_only')
        export_file = options.get('export')
        
        # Calculate the date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        self.stdout.write(f"Analyzing telemetry from {start_date.date()} to {end_date.date()}")
        
        # Base queryset
        queryset = VSCodeTelemetryEvent.objects.filter(
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )
        
        # Apply filters
        if event_type:
            queryset = queryset.filter(event_name=event_type)
        
        if errors_only:
            queryset = queryset.filter(event_name='shareError')
        
        # Get total event count
        total_events = queryset.count()
        self.stdout.write(f"Total events: {total_events}")
        
        # Analyze event types
        event_types = queryset.values('event_name').annotate(
            count=Count('id'),
            percentage=Count('id') * 100.0 / total_events
        ).order_by('-count')
        
        self.stdout.write("\nEvent Types:")
        for et in event_types:
            self.stdout.write(f"  {et['event_name']}: {et['count']} ({et['percentage']:.1f}%)")
        
        # Language distribution
        languages = queryset.exclude(language='').values('language').annotate(
            count=Count('id'),
            percentage=Count('id') * 100.0 / total_events
        ).order_by('-count')[:10]
        
        self.stdout.write("\nTop Languages:")
        for lang in languages:
            self.stdout.write(f"  {lang['language']}: {lang['count']} ({lang['percentage']:.1f}%)")
        
        # VS Code version distribution
        versions = queryset.exclude(vs_code_version='').values('vs_code_version').annotate(
            count=Count('id'),
            percentage=Count('id') * 100.0 / total_events
        ).order_by('-count')[:5]
        
        self.stdout.write("\nVS Code Versions:")
        for ver in versions:
            self.stdout.write(f"  {ver['vs_code_version']}: {ver['count']} ({ver['percentage']:.1f}%)")
        
        # Show error analysis if errors exist
        error_events = queryset.filter(event_name='shareError')
        if error_events.exists():
            self.stdout.write("\nError Analysis:")
            self.stdout.write(f"  Total Errors: {error_events.count()}")
            
            # Group errors
            error_types = defaultdict(int)
            for event in error_events:
                error_msg = event.error_message or "Unknown error"
                # Simplify error message for grouping
                simplified_error = error_msg.split(':')[0] if ':' in error_msg else error_msg
                error_types[simplified_error] += 1
            
            for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:10]:
                self.stdout.write(f"  {error_type}: {count}")
        
        # Daily activity
        self.stdout.write("\nDaily Activity:")
        dates = queryset.values('timestamp__date').annotate(
            count=Count('id')
        ).order_by('timestamp__date')
        
        for date_data in dates:
            self.stdout.write(f"  {date_data['timestamp__date']}: {date_data['count']} events")
        
        # Unique users
        unique_users = queryset.values('client_id').distinct().count()
        self.stdout.write(f"\nUnique Users: {unique_users}")
        
        # Export to CSV if requested
        if export_file:
            self.export_to_csv(queryset, export_file)
            self.stdout.write(f"Data exported to {export_file}")
    
    def export_to_csv(self, queryset, filename):
        """Export telemetry data to CSV file"""
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['timestamp', 'event_name', 'client_id', 'vs_code_version', 
                        'language', 'code_length', 'error_message']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for event in queryset:
                writer.writerow({
                    'timestamp': event.timestamp.isoformat(),
                    'event_name': event.event_name,
                    'client_id': event.client_id,
                    'vs_code_version': event.vs_code_version,
                    'language': event.language,
                    'code_length': event.code_length,
                    'error_message': event.error_message
                })