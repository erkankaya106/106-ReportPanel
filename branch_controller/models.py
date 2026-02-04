import secrets

from django.db import models
import uuid

class Bayi(models.Model):
    name = models.CharField(max_length=255, verbose_name="Bayi Adı")
    branch_id = models.CharField(max_length=50, unique=True, verbose_name="Branch ID")
    secret_key = models.CharField(max_length=128, verbose_name="Secret Key")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.branch_id})"

    @classmethod
    def generate_secret_key(cls) -> str:
        """Güçlü, random secret key üretir."""
        return secrets.token_urlsafe(32)  # ~43 karakter, URL-safe

    def save(self, *args, **kwargs):
        # Boşsa otomatik üret
        if not self.secret_key:
            self.secret_key = self.generate_secret_key()
        super().save(*args, **kwargs)

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class CSVValidationError(models.Model):
    """
    CSV dosyalarındaki format hatalarını ÖZET olarak kaydeder.
    Her dosya için TEK kayıt, hatalar JSON formatında gruplu.
    """
    
    # Temel bilgiler
    bayi = models.ForeignKey(Bayi, on_delete=models.SET_NULL, null=True, blank=True)
    filename = models.CharField(max_length=255, db_index=True)
    validation_date = models.DateField(db_index=True, null=True, blank=True, help_text="CSV'nin ait olduğu tarih")
    
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
        unique_together = [['bayi', 'filename', 'validation_date']]
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