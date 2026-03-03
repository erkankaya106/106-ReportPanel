# Generated manually for secret key encryption feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('branch_controller', '0002_alter_bayi_options_alter_transferlog_options'),
    ]

    operations = [
        # secret_key field'ının max_length'ini 128'den 500'e çıkar (encrypt edilmiş hali daha uzun)
        migrations.AlterField(
            model_name='bayi',
            name='secret_key',
            field=models.CharField(max_length=500, verbose_name='Secret Key'),
        ),
        # _temp_secret_key field'ını ekle
        migrations.AddField(
            model_name='bayi',
            name='_temp_secret_key',
            field=models.CharField(blank=True, editable=False, max_length=128, null=True, verbose_name='Geçici Secret Key'),
        ),
    ]
