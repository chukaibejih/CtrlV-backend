# Generated by Django 5.1.5 on 2025-02-25 15:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("snippets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SnippetMetrics",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField(unique=True)),
                ("total_snippets", models.PositiveIntegerField(default=0)),
                ("total_views", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "snippet_metrics",
            },
        ),
    ]
