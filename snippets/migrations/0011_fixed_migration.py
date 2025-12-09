from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("snippets", "0010_snippet_consumed_at_snippet_is_consumed"),
    ]

    # Fields/index were already added in 0009; keep this migration as a no-op to avoid duplicate column errors.
    operations = []
