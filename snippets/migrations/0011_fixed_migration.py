from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("snippets", "0010_snippet_consumed_at_snippet_is_consumed"),
    ]

    operations = [
        migrations.AddField(
            model_name="snippet",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="snippet",
            name="public_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddIndex(
            model_name="snippet",
            index=models.Index(
                fields=["is_public", "expires_at", "created_at"],
                name="snippets_is_publ_04ed86_idx",
            ),
        ),
    ]