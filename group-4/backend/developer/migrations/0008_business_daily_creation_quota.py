from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("developer", "0007_business_rate_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessapiaccess",
            name="daily_creation_quota",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="BusinessDailyCreationUsage",
            fields=[
                ("id", models.CharField(max_length=47, primary_key=True, serialize=False)),
                ("used", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "business_daily_creation_usage"},
        ),
    ]
