# Generated manually for encryption support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('branch_controller', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bayi',
            name='secret_key',
            field=models.TextField(verbose_name='Secret Key (Encrypted)'),
        ),
    ]
