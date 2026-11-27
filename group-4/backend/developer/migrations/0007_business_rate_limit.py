from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("developer", "0006_merge_dashboard_and_webhooks"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessapiaccess",
            name="rate_limit_requests_per_minute",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="businessapiaccess",
            name="pending_rate_limit_requests_per_minute",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="businessapiaccess",
            name="rate_limit_effective_window",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
