from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("branch_controller", "0007_csvvalidationerror_provider_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferlog",
            name="signature",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="HMAC-SHA256 imzası — replay saldırı koruması için saklanır",
                max_length=64,
                null=True,
            ),
        ),
    ]
