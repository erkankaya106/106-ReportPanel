"""
Validation Logger - CSV validation sonuçlarını ÖZET olarak DB ve log dosyasına kaydeder.

Yeni özellikler:
- Dosya bazında tek özet kayıt
- Gruplu hata detayları (JSON)
- Akıllı mesaj formatı
- Doğruluk oranı hesaplama
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Optional

from django.conf import settings

from .models import CSVValidationError as CSVValidationErrorModel, Bayi
from .csv_validator import CSVValidator
from .message_formatter import SmartMessageFormatter


class ValidationLogger:
    """CSV validation sonuçlarını ÖZET olarak DB ve dosyaya kaydeder"""
    
    def __init__(self, log_dir: Optional[Path] = None):
        """
        Args:
            log_dir: Log dosyalarının kaydedileceği klasör (default: BASE_DIR/logs)
        """
        if log_dir is None:
            log_dir = settings.BASE_DIR / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Günlük log dosyası
        today = datetime.now().strftime('%Y-%m-%d')
        self.log_file = self.log_dir / f"csv_validation_{today}.json"
        
        # Session bilgileri
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.session_start = datetime.now()
    
    def log_file_validation_summary(
        self,
        filename: str,
        validation_date: date,
        validator: CSVValidator,
        bayi: Optional[Bayi] = None,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        """
        Dosya validation özetini DB ve log dosyasına kaydeder.
        
        Args:
            filename: CSV dosya adı
            validation_date: CSV'nin ait olduğu tarih
            validator: Validation sonuçlarını içeren validator instance
            bayi: İlgili bayi (opsiyonel)
            save_to_db: DB'ye kaydetme durumu (dry-run için False)
        
        Returns:
            Özet bilgileri dict
        """
        # Gruplu hata detaylarını al
        error_summary = validator.get_grouped_errors()
        
        # İstatistikleri hesapla
        total_rows = validator.validated_rows
        error_count = len(validator.errors)
        accuracy_rate = SmartMessageFormatter.calculate_accuracy_rate(total_rows, error_count)
        
        # Akıllı mesaj oluştur
        summary_message = SmartMessageFormatter.format_summary_message(
            filename=filename,
            total_rows=total_rows,
            error_count=error_count,
            accuracy_rate=accuracy_rate,
            error_summary=error_summary
        )
        
        # DB'ye kaydet (tek kayıt)
        if save_to_db:
            try:
                # Unique constraint'e göre update or create
                obj, created = CSVValidationErrorModel.objects.update_or_create(
                    bayi=bayi,
                    filename=filename,
                    validation_date=validation_date,
                    defaults={
                        'total_rows': total_rows,
                        'error_count': error_count,
                        'accuracy_rate': accuracy_rate,
                        'error_summary': error_summary,
                        'summary_message': summary_message,
                    }
                )
                action = "created" if created else "updated"
                print(f"[ValidationLogger] DB record {action}: {filename}")
            except Exception as e:
                print(f"[ValidationLogger] DB kayıt hatası: {e}")
        
        # JSON log dosyasına özet yaz
        json_summary = SmartMessageFormatter.create_json_summary(
            filename=filename,
            total_rows=total_rows,
            error_count=error_count,
            accuracy_rate=accuracy_rate,
            error_summary=error_summary
        )
        json_summary['session_id'] = self.session_id
        json_summary['validation_date'] = str(validation_date)
        json_summary['branch_id'] = bayi.branch_id if bayi else None
        json_summary['timestamp'] = datetime.now().isoformat()
        
        self._write_to_log_file(json_summary)
        
        return {
            'filename': filename,
            'total_rows': total_rows,
            'error_count': error_count,
            'accuracy_rate': accuracy_rate,
            'category': SmartMessageFormatter.get_accuracy_category(accuracy_rate)[0]
        }
    
    def log_session_summary(
        self,
        total_files: int,
        processed_files: int,
        total_rows: int,
        total_errors: int,
        processing_time: float,
        category_stats: Dict[str, int]
    ):
        """Session özetini log dosyasına kaydeder"""
        self._write_to_log_file({
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'type': 'session_summary',
            'session_start': self.session_start.isoformat(),
            'session_end': datetime.now().isoformat(),
            'total_files': total_files,
            'processed_files': processed_files,
            'total_rows': total_rows,
            'total_errors': total_errors,
            'category_stats': category_stats,
            'processing_time_seconds': round(processing_time, 2),
            'rows_per_second': round(total_rows / processing_time, 2) if processing_time > 0 else 0
        })
    
    def _write_to_log_file(self, log_data: Dict[str, Any]):
        """Log verisini JSON formatında dosyaya yazar"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json.dump(log_data, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            print(f"[ValidationLogger] Log dosyası yazma hatası: {e}")
    
    def get_log_file_path(self) -> Path:
        """Log dosyasının yolunu döndürür"""
        return self.log_file
    
    @staticmethod
    def read_log_file(log_file_path: Path) -> List[Dict[str, Any]]:
        """
        Log dosyasını okur ve parse eder.
        
        Args:
            log_file_path: Log dosyası yolu
        
        Returns:
            Log kayıtları listesi
        """
        logs = []
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        logs.append(json.loads(line))
        except Exception as e:
            print(f"[ValidationLogger] Log dosyası okuma hatası: {e}")
        
        return logs
    
    @staticmethod
    def get_error_statistics_from_db(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        branch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Veritabanından hata istatistiklerini çeker.
        
        Args:
            start_date: Başlangıç tarihi (opsiyonel)
            end_date: Bitiş tarihi (opsiyonel)
            branch_id: Branch ID filtresi (opsiyonel)
        
        Returns:
            İstatistik bilgileri
        """
        from django.db.models import Sum, Avg, Count
        
        queryset = CSVValidationErrorModel.objects.all()
        
        if start_date:
            queryset = queryset.filter(detected_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(detected_at__lte=end_date)
        if branch_id:
            queryset = queryset.filter(bayi__branch_id=branch_id)
        
        # Genel istatistikler
        stats = queryset.aggregate(
            total_files=Count('id'),
            total_errors=Sum('error_count'),
            avg_accuracy=Avg('accuracy_rate'),
            total_rows=Sum('total_rows')
        )
        
        # Doğruluk kategorilerine göre grupla
        category_counts = {
            'perfect': queryset.filter(accuracy_rate=100.0).count(),
            'good': queryset.filter(accuracy_rate__gte=80.0, accuracy_rate__lt=100.0).count(),
            'medium': queryset.filter(accuracy_rate__gte=50.0, accuracy_rate__lt=80.0).count(),
            'critical': queryset.filter(accuracy_rate__lt=50.0).count(),
        }
        
        # En çok hatalı dosyalar
        top_error_files = queryset.order_by('-error_count')[:10].values(
            'filename', 'error_count', 'accuracy_rate'
        )
        
        return {
            'total_files': stats['total_files'] or 0,
            'total_errors': stats['total_errors'] or 0,
            'total_rows': stats['total_rows'] or 0,
            'avg_accuracy': round(float(stats['avg_accuracy'] or 0), 2),
            'category_counts': category_counts,
            'top_error_files': list(top_error_files)
        }
