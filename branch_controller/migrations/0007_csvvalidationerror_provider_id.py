# Generated migration — adds provider_id to CSVValidationError and updates unique_together

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("branch_controller", "0006_update_csvvalidationerror_to_summary"),
    ]

    operations = [
        # 1. Önce eski unique_together'ı kaldır
        migrations.AlterUniqueTogether(
            name="csvvalidationerror",
            unique_together=set(),
        ),
        # 2. provider_id alanını ekle
        migrations.AddField(
            model_name="csvvalidationerror",
            name="provider_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Provider ID (örn: 01, 02)",
                max_length=10,
            ),
        ),
        # 3. Yeni unique_together'ı ekle (provider_id dahil)
        migrations.AlterUniqueTogether(
            name="csvvalidationerror",
            unique_together={("bayi", "filename", "provider_id", "validation_date")},
        ),
    ]
