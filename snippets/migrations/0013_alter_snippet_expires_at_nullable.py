from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('snippets', '0012_remove_snippet_encryption_salt_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='snippet',
            name='expires_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
