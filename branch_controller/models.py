import secrets
import hashlib
import base64

from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet
import uuid


def _get_fernet():
    """Fernet instance'ı döndürür. ENCRYPTION_KEY'i kullanır."""
    encryption_key = settings.ENCRYPTION_KEY.encode('utf-8')
    # Fernet 32-byte key bekler, eğer daha uzunsa hash'le
    if len(encryption_key) != 32:
        encryption_key = hashlib.sha256(encryption_key).digest()
    else:
        encryption_key = encryption_key[:32]
    # Fernet base64-encoded key bekler
    fernet_key = base64.urlsafe_b64encode(encryption_key)
    return Fernet(fernet_key)


def _is_encrypted(value: str) -> bool:
    """Bir değerin Fernet ile encrypt edilmiş olup olmadığını kontrol eder."""
    if not value:
        return False
    try:
        # Fernet token'ları base64 formatında ve belirli bir yapıya sahiptir
        # Token formatı: base64(version + timestamp + IV + ciphertext + HMAC)
        decoded = base64.urlsafe_b64decode(value)
        # Fernet token en az 57 byte olmalı (1 byte version + 8 byte timestamp + 16 byte IV + en az 32 byte)
        return len(decoded) >= 57
    except Exception:
        return False


class Bayi(models.Model):
    name = models.CharField(max_length=255, verbose_name="Bayi Adı")
    branch_id = models.CharField(max_length=50, unique=True, verbose_name="Branch ID")
    secret_key = models.CharField(max_length=500, verbose_name="Secret Key")  # Encrypt edilmiş hali daha uzun olabilir
    _temp_secret_key = models.CharField(max_length=128, null=True, blank=True, editable=False, verbose_name="Geçici Secret Key")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.branch_id})"

    @classmethod
    def generate_secret_key(cls) -> str:
        """Güçlü, random secret key üretir."""
        return secrets.token_urlsafe(32)  # ~43 karakter, URL-safe

    def get_secret_key(self) -> str:
        """
        HMAC doğrulaması için decrypt edilmiş secret key döndürür.
        Eğer secret_key zaten düz metinse (eski kayıtlar için), olduğu gibi döndürür.
        """
        if not self.secret_key:
            return ""
        
        # Eğer encrypt edilmişse decrypt et
        if _is_encrypted(self.secret_key):
            try:
                fernet = _get_fernet()
                return fernet.decrypt(self.secret_key.encode('utf-8')).decode('utf-8')
            except Exception:
                # Decrypt başarısız olursa, eski format olabilir
                return self.secret_key
        else:
            # Eski kayıtlar için düz metin olabilir
            return self.secret_key

    def save(self, *args, **kwargs):
        # _temp_secret_key'i sakla (save sonrası temizlemek için)
        temp_key = self._temp_secret_key
        
        # İlk kayıt: secret_key boşsa ve _temp_secret_key varsa
        if not self.secret_key and self._temp_secret_key:
            # _temp_secret_key'i encrypt ederek secret_key'e kaydet
            fernet = _get_fernet()
            self.secret_key = fernet.encrypt(self._temp_secret_key.encode('utf-8')).decode('utf-8')
        # Secret key düz metinse (eski kayıt veya manuel giriş), encrypt et
        elif self.secret_key and not _is_encrypted(self.secret_key):
            fernet = _get_fernet()
            self.secret_key = fernet.encrypt(self.secret_key.encode('utf-8')).decode('utf-8')
        # _temp_secret_key varsa (yeni key üretildi), bunu secret_key'e encrypt ederek kaydet
        elif self._temp_secret_key:
            fernet = _get_fernet()
            self.secret_key = fernet.encrypt(self._temp_secret_key.encode('utf-8')).decode('utf-8')
        
        # _temp_secret_key'i None yap (DB'ye kaydedilmesin, sadece memory'de kalsın)
        # Çünkü admin panelinde gösterilmesi için memory'de kalması gerekiyor
        # DB'ye kaydetmeden önce None yapıyoruz
        if temp_key:
            # Önce save et (secret_key encrypt edilmiş olarak kaydedilecek)
            super().save(*args, **kwargs)
            # Sonra _temp_secret_key'i DB'den temizle ama memory'de tut (admin'de gösterilmek için)
            Bayi.objects.filter(pk=self.pk).update(_temp_secret_key=None)
            # Memory'deki değeri koru (admin response'da gösterilmek için)
            # Bu değer bir sonraki request'te zaten yok olacak
        else:
            super().save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Alt Bayiler"

class TransferLog(models.Model):
    STATUS_CHOICES = [
        ('SUCCESS', 'Başarılı'),
        ('FAILED', 'Hatalı'),
        ('PENDING', 'İşleniyor'),
    ]
    bayi = models.ForeignKey(Bayi, on_delete=models.SET_NULL, null=True)
    filename = models.CharField(max_length=255)
    s3_path = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True)
    # Replay saldırı koruması: HMAC imzası kaydedilir, 5 dk içinde aynı imza reddedilir
    signature = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Bayi Data Transfer Logları"


class CSVValidationError(models.Model):
    """
    CSV dosyalarındaki format hatalarını ÖZET olarak kaydeder.
    Her dosya için TEK kayıt, hatalar JSON formatında gruplu.
    """
    
    # Temel bilgiler
    bayi = models.ForeignKey(Bayi, on_delete=models.SET_NULL, null=True, blank=True)
    filename = models.CharField(max_length=255, db_index=True)
    provider_id = models.CharField(max_length=10, default="", blank=True, db_index=True, help_text="Provider ID (örn: 01, 02)")
    validation_date = models.DateField(db_index=True, null=True, blank=True, help_text="CSV'nin ait olduğu tarih (date= partition)")
    
    # İstatistikler
    total_rows = models.IntegerField(default=0, help_text="Toplam satır sayısı (header hariç)")
    error_count = models.IntegerField(default=0, help_text="Toplam hata sayısı")
    accuracy_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        default=0.00,
        help_text="Doğruluk oranı (0.00 - 100.00)"
    )
    
    # Gruplu hata detayları (JSON)
    error_summary = models.JSONField(
        default=dict,
        help_text="Hata türlerine göre gruplu detaylar"
    )
    # Örnek yapı:
    # {
    #   "EMPTY_FIELD": {
    #     "roundId bos": {"count": 3, "rows": [5, 7, 12]},
    #     "betAmount bos": {"count": 2, "rows": [15, 20]}
    #   },
    #   "DECIMAL": {
    #     "betAmount nokta kullanimi": {"count": 5, "rows": [3, 8, 11, 14, 18]}
    #   }
    # }
    
    # Kısaltılmış mesaj (max 3500 karakter)
    summary_message = models.TextField(default="", blank=True, help_text="Formatlanmış özet mesaj")
    
    # Zaman damgası
    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['bayi', 'validation_date']),
            models.Index(fields=['accuracy_rate']),
            models.Index(fields=['validation_date', 'detected_at']),
        ]
        unique_together = [['bayi', 'filename', 'provider_id', 'validation_date']]
        verbose_name = "CSV Validation Özeti"
        verbose_name_plural = "CSV Validation Özetleri"
    
    def __str__(self):
        return f"{self.filename} - %{self.accuracy_rate} doğruluk ({self.error_count} hata)"
    
    def get_accuracy_category(self):
        """Doğruluk kategorisi döndürür"""
        if self.accuracy_rate == 100.0:
            return "Mükemmel"
        elif self.accuracy_rate >= 80.0:
            return "İyi"
        elif self.accuracy_rate >= 50.0:
            return "Orta"
        else:
            return "Kritik"
    
    def is_perfect(self):
        """Hiç hata var mı?"""
        return self.error_count == 0 and self.accuracy_rate == 100.0