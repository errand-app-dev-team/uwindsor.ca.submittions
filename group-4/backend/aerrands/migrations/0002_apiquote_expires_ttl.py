from django.db import migrations


def create_expires_at_ttl_index(apps, schema_editor):
    collection = schema_editor.connection.database["api_quotes"]

    collection.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="api_quotes_expires_at_ttl",
    )


def remove_expires_at_ttl_index(apps, schema_editor):
    collection = schema_editor.connection.database["api_quotes"]

    collection.drop_index("api_quotes_expires_at_ttl")


class Migration(migrations.Migration):

    dependencies = [
        ("aerrands", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_expires_at_ttl_index,
            remove_expires_at_ttl_index,
        ),
    ]