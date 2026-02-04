# Generated manually to revert encryption and convert to plain text

from django.db import migrations, models


def decrypt_existing_keys(apps, schema_editor):
    """Mevcut encrypted secret_key'leri decrypt et (eğer mümkünse)."""
    Bayi = apps.get_model('branch_controller', 'Bayi')
    
    # Encryption key'i al (eğer varsa)
    try:
        from django.conf import settings
        from cryptography.fernet import Fernet
        
        encryption_key = getattr(settings, 'ENCRYPTION_KEY', None)
        if encryption_key:
            if isinstance(encryption_key, str):
                encryption_key = encryption_key.encode()
            
            f = Fernet(encryption_key)
            
            for bayi in Bayi.objects.all():
                if bayi.secret_key and bayi.secret_key.startswith('gAAAAAB'):
                    # Encrypted görünüyorsa decrypt et
                    try:
                        decrypted = f.decrypt(bayi.secret_key.encode()).decode()
                        Bayi.objects.filter(pk=bayi.pk).update(secret_key=decrypted)
                    except Exception as e:
                        # Decrypt edilemezse, olduğu gibi bırak (kullanıcı manuel yeniden oluşturabilir)
                        print(f"Warning: Could not decrypt secret_key for bayi {bayi.pk}: {e}")
        else:
            # ENCRYPTION_KEY yoksa, encrypted verileri olduğu gibi bırak
            print("Warning: ENCRYPTION_KEY not found, encrypted secret_keys will remain encrypted")
    except ImportError:
        # cryptography modülü yoksa, olduğu gibi bırak
        print("Warning: cryptography module not available, encrypted secret_keys will remain encrypted")
    except Exception as e:
        print(f"Warning: Error during decryption: {e}")


def reverse_decrypt(apps, schema_editor):
    """Reverse migration: Bu migration geri alınamaz, çünkü encryption kaldırıldı."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('branch_controller', '0003_encrypt_existing_secret_keys'),
    ]

    operations = [
        migrations.RunPython(decrypt_existing_keys, reverse_decrypt),
        migrations.AlterField(
            model_name='bayi',
            name='secret_key',
            field=models.CharField(max_length=128, verbose_name='Secret Key'),
        ),
    ]
