from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from decouple import config

class Command(BaseCommand):
    help = 'Creates a superuser from environment variables'

    def handle(self, *args, **options):
        User = get_user_model()

        first_name = config('DJANGO_SUPERUSER_FIRST_NAME', default='Ibejih')
        last_name = config('DJANGO_SUPERUSER_LAST_NAME', default='Daniel')
        email = config('DJANGO_SUPERUSER_EMAIL', default='ibejih@ctrlv.com')
        password = config('DJANGO_SUPERUSER_PASSWORD', default='manifest37')

        if not all([first_name, last_name, email, password]):
            self.stdout.write(self.style.ERROR('Missing one or more required environment variables'))
            return

        try:
            user, created = User.objects.get_or_create(email=email, defaults={
                'first_name': first_name,
                'last_name': last_name,
                'is_staff': True,
                'is_superuser': True,
            })
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS('Successfully created new superuser'))
            else:
                self.stdout.write(self.style.WARNING('Superuser already exists'))

        except IntegrityError as e:
            self.stdout.write(self.style.ERROR(f'Error creating superuser: {str(e)}'))
