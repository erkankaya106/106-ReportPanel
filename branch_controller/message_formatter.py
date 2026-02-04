"""
Smart Message Formatter - CSV validation hatalarını akıllı şekilde gruplar ve formatlar.

Özellikler:
- Bayi bazında hata gruplama
- Her hata türü için max 10 satır numarası
- Her bayi için max 15 hata türü
- Toplam 3500 karakter limiti
- Güzel formatlanmış çıktılar
"""

from typing import Dict, List, Any
from collections import defaultdict


class SmartMessageFormatter:
    """CSV validation hatalarını akıllı şekilde formatlar ve kısaltır"""
    
    # Maksimum limitler
    MAX_MESSAGE_LENGTH = 3500
    MAX_ERROR_TYPES_PER_FILE = 15
    MAX_ROW_NUMBERS_PER_ERROR = 10
    
    # Hata türü öncelikleri (yüksek → düşük)
    ERROR_PRIORITY = {
        'HEADER': 1,
        'EMPTY_FIELD': 2,
        'DATE_FORMAT': 3,
        'DECIMAL': 4,
        'NUMERIC': 5,
        'STATUS': 6,
        'DELIMITER': 7,
    }
    
    # Hata türü açıklamaları
    ERROR_DESCRIPTIONS = {
        'HEADER': 'Baslik Hatasi',
        'DELIMITER': 'Alan Ayraci Hatasi',
        'DECIMAL': 'Decimal Ayraci Hatasi',
        'DATE_FORMAT': 'Tarih Formati Hatasi',
        'NUMERIC': 'Sayisal Deger Hatasi',
        'STATUS': 'Status Degeri Hatasi',
        'EMPTY_FIELD': 'Bos Alan Hatasi',
    }
    
    @staticmethod
    def group_errors_by_type_and_detail(errors: List[Any]) -> Dict[str, Dict[str, Dict]]:
        """
        Hataları tip ve detaya göre gruplar.
        
        Returns:
            {
                "EMPTY_FIELD": {
                    "roundId bos": {"count": 3, "rows": [5, 7, 12]},
                    "betAmount bos": {"count": 2, "rows": [15, 20]}
                },
                "DECIMAL": {
                    "betAmount nokta kullanimi": {"count": 5, "rows": [3, 8, 11, 14, 18]}
                }
            }
        """
        grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "rows": []}))
        
        for error in errors:
            error_type = error.error_type
            # Hata detayını kısalt ve normalize et
            detail = SmartMessageFormatter._simplify_error_detail(error.error_detail)
            
            grouped[error_type][detail]["count"] += 1
            grouped[error_type][detail]["rows"].append(error.row_number)
        
        # Satır numaralarını sırala
        for error_type in grouped:
            for detail in grouped[error_type]:
                grouped[error_type][detail]["rows"].sort()
        
        return dict(grouped)
    
    @staticmethod
    def _simplify_error_detail(detail: str) -> str:
        """Hata detayını kısaltır ve sadeleştirir"""
        # Türkçe karakterleri normalize et
        detail = detail.replace('ı', 'i').replace('ş', 's').replace('ğ', 'g')
        detail = detail.replace('ü', 'u').replace('ö', 'o').replace('ç', 'c')
        detail = detail.replace('İ', 'I').replace('Ş', 'S').replace('Ğ', 'G')
        detail = detail.replace('Ü', 'U').replace('Ö', 'O').replace('Ç', 'C')
        
        # Uzun mesajları kısalt
        if len(detail) > 80:
            detail = detail[:77] + "..."
        
        return detail
    
    @staticmethod
    def format_summary_message(
        filename: str,
        total_rows: int,
        error_count: int,
        accuracy_rate: float,
        error_summary: Dict[str, Dict[str, Dict]]
    ) -> str:
        """
        Özet mesajı formatlar.
        
        Args:
            filename: Dosya adı
            total_rows: Toplam satır sayısı
            error_count: Hata sayısı
            accuracy_rate: Doğruluk oranı (0-100)
            error_summary: Gruplu hata özeti
        
        Returns:
            Formatlanmış mesaj (max 3500 karakter)
        """
        lines = []
        
        # Header
        lines.append(f"DOSYA: {filename}")
        lines.append(f"Dogruluk Orani: {accuracy_rate:.2f}% ({error_count}/{total_rows} satir hatali)")
        lines.append("")
        
        if error_count == 0:
            lines.append("Hata bulunamadi. Dosya formata uygun.")
            return "\n".join(lines)
        
        lines.append("HATA DETAYLARI:")
        lines.append("=" * 60)
        lines.append("")
        
        # Hata türlerini önceliğe göre sırala
        sorted_error_types = sorted(
            error_summary.keys(),
            key=lambda x: SmartMessageFormatter.ERROR_PRIORITY.get(x, 99)
        )
        
        # Her hata türü için max 15 tür göster
        shown_error_types = 0
        remaining_types = 0
        
        for error_type in sorted_error_types:
            if shown_error_types >= SmartMessageFormatter.MAX_ERROR_TYPES_PER_FILE:
                remaining_types += 1
                continue
            
            error_details = error_summary[error_type]
            type_description = SmartMessageFormatter.ERROR_DESCRIPTIONS.get(error_type, error_type)
            total_errors_of_type = sum(d["count"] for d in error_details.values())
            
            lines.append(f"{type_description} ({total_errors_of_type} adet)")
            lines.append("-" * 60)
            
            # Her detay için satır numaralarını göster
            for detail, info in list(error_details.items())[:5]:  # Max 5 detail per type
                count = info["count"]
                rows = info["rows"][:SmartMessageFormatter.MAX_ROW_NUMBERS_PER_ERROR]
                
                if len(info["rows"]) > SmartMessageFormatter.MAX_ROW_NUMBERS_PER_ERROR:
                    remaining = len(info["rows"]) - SmartMessageFormatter.MAX_ROW_NUMBERS_PER_ERROR
                    rows_str = ", ".join(map(str, rows)) + f" ... (+{remaining} satir daha)"
                else:
                    rows_str = ", ".join(map(str, rows))
                
                lines.append(f"  - {detail}: Satirlar {rows_str} ({count} adet)")
            
            if len(error_details) > 5:
                remaining_details = len(error_details) - 5
                lines.append(f"  ... ve {remaining_details} farkli hata daha")
            
            lines.append("")
            shown_error_types += 1
        
        if remaining_types > 0:
            lines.append(f"... ve {remaining_types} farkli hata turu daha")
            lines.append("")
        
        # Mesajı birleştir
        message = "\n".join(lines)
        
        # 3500 karakter limitini kontrol et
        if len(message) > SmartMessageFormatter.MAX_MESSAGE_LENGTH:
            message = message[:SmartMessageFormatter.MAX_MESSAGE_LENGTH - 50]
            message += "\n\n... (Mesaj cok uzun, kisaltildi)"
        
        return message
    
    @staticmethod
    def get_accuracy_category(accuracy_rate: float) -> tuple:
        """
        Doğruluk oranına göre kategori döndürür.
        
        Returns:
            (category_name, emoji/symbol)
        """
        if accuracy_rate == 100.0:
            return ("Mukemmel", "OK")
        elif accuracy_rate >= 80.0:
            return ("Iyi", "GOOD")
        elif accuracy_rate >= 50.0:
            return ("Orta", "WARN")
        else:
            return ("Kritik", "ERROR")
    
    @staticmethod
    def format_console_output(
        filename: str,
        total_rows: int,
        error_count: int,
        accuracy_rate: float
    ) -> str:
        """Console için kısa özet formatlar"""
        category, symbol = SmartMessageFormatter.get_accuracy_category(accuracy_rate)
        
        if accuracy_rate == 100.0:
            return f"[{symbol}] {filename}: {total_rows} satir, 0 hata (%{accuracy_rate:.1f} - {category})"
        else:
            return f"[{symbol}] {filename}: {total_rows} satir, {error_count} hata (%{accuracy_rate:.1f} - {category})"
    
    @staticmethod
    def calculate_accuracy_rate(total_rows: int, error_count: int) -> float:
        """Doğruluk oranını hesaplar (0-100 arası)"""
        if total_rows == 0:
            return 100.0
        
        correct_rows = total_rows - error_count
        accuracy = (correct_rows / total_rows) * 100.0
        
        # 0-100 arasında sınırla
        return max(0.0, min(100.0, accuracy))
    
    @staticmethod
    def create_json_summary(
        filename: str,
        total_rows: int,
        error_count: int,
        accuracy_rate: float,
        error_summary: Dict[str, Dict[str, Dict]]
    ) -> Dict[str, Any]:
        """JSON log için özet oluşturur"""
        return {
            "filename": filename,
            "total_rows": total_rows,
            "error_count": error_count,
            "accuracy_rate": round(accuracy_rate, 2),
            "error_summary": error_summary,
            "category": SmartMessageFormatter.get_accuracy_category(accuracy_rate)[0]
        }
