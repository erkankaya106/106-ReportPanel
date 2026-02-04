# Generated manually to encrypt existing plain text secret keys

from django.db import migrations
from cryptography.fernet import Fernet
from django.conf import settings


def encrypt_existing_keys(apps, schema_editor):
    """Mevcut plain text secret_key'leri encrypt et."""
    Bayi = apps.get_model('branch_controller', 'Bayi')
    
    # Encryption key'i al
    encryption_key = settings.ENCRYPTION_KEY
    if isinstance(encryption_key, str):
        encryption_key = encryption_key.encode()
    
    try:
        f = Fernet(encryption_key)
    except Exception as e:
        # Eğer encryption key geçersizse, migration'ı atla
        print(f"Warning: Encryption key invalid, skipping encryption migration: {e}")
        return
    
    for bayi in Bayi.objects.all():
        if bayi.secret_key and not bayi.secret_key.startswith('gAAAAAB'):
            # Plain text görünüyorsa encrypt et
            try:
                encrypted = f.encrypt(bayi.secret_key.encode()).decode()
                Bayi.objects.filter(pk=bayi.pk).update(secret_key=encrypted)
            except Exception as e:
                print(f"Warning: Could not encrypt secret_key for bayi {bayi.pk}: {e}")


def reverse_encrypt(apps, schema_editor):
    """Reverse migration: decrypt edip plain text'e çevir (gerekirse)."""
    Bayi = apps.get_model('branch_controller', 'Bayi')
    
    encryption_key = settings.ENCRYPTION_KEY
    if isinstance(encryption_key, str):
        encryption_key = encryption_key.encode()
    
    try:
        f = Fernet(encryption_key)
    except Exception:
        return
    
    for bayi in Bayi.objects.all():
        if bayi.secret_key and bayi.secret_key.startswith('gAAAAAB'):
            # Encrypted görünüyorsa decrypt et
            try:
                decrypted = f.decrypt(bayi.secret_key.encode()).decode()
                Bayi.objects.filter(pk=bayi.pk).update(secret_key=decrypted)
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('branch_controller', '0002_alter_bayi_secret_key'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_keys, reverse_encrypt),
    ]
