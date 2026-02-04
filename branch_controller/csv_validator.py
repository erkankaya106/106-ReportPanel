"""
CSV Validator - CSV dosyalarındaki format hatalarını tespit eder.

7 ana kontrol kuralı:
1. CSV Başlık Kontrolü
2. Alan Ayracı Kontrolü (;)
3. Decimal Ayracı Kontrolü (,)
4. Tarih Formatı Kontrolü (YYYY-MM-DD HH:MM:SS)
5. Sayısal Değer Kontrolü (negatif değer)
6. Status Değeri Kontrolü (won/lost)
7. Boş Değer Kontrolü
"""

import io
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple, BinaryIO


class CSVValidationError:
    """Bir validasyon hatasını temsil eder"""
    
    def __init__(self, row_number: int, error_type: str, error_detail: str, raw_row: str = ""):
        self.row_number = row_number
        self.error_type = error_type
        self.error_detail = error_detail
        self.raw_row = raw_row
    
    def __repr__(self):
        return f"<CSVValidationError row={self.row_number} type={self.error_type}>"


class CSVValidator:
    """CSV dosyalarını 7 kurala göre validate eder"""
    
    # Beklenen CSV header'ları
    EXPECTED_HEADERS = ['roundId', 'gameId', 'createDate', 'updateDate', 'betAmount', 'winAmount', 'status']
    
    # Beklenen alan ayracı
    FIELD_DELIMITER = ';'
    
    # Beklenen decimal ayracı
    DECIMAL_SEPARATOR = ','
    
    # Geçerli status değerleri
    VALID_STATUSES = ['won', 'lost']
    
    # Tarih formatı pattern
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
    DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
    
    def __init__(self):
        self.errors: List[CSVValidationError] = []
        self.validated_rows = 0
    
    def validate_file(self, file_path: str) -> Tuple[bool, List[CSVValidationError]]:
        """
        Bir CSV dosyasını tamamen validate eder.
        
        Returns:
            (is_valid, errors) tuple'ı
        """
        self.errors = []
        self.validated_rows = 0
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
                if not lines:
                    self.errors.append(CSVValidationError(
                        row_number=0,
                        error_type='HEADER',
                        error_detail='CSV dosyası boş',
                        raw_row=''
                    ))
                    return False, self.errors
                
                # Header kontrolü
                header_line = lines[0].strip()
                if not self._validate_header(header_line):
                    self.errors.append(CSVValidationError(
                        row_number=1,
                        error_type='HEADER',
                        error_detail=f'Header beklenen formatta değil. Beklenen: {self.EXPECTED_HEADERS}',
                        raw_row=header_line
                    ))
                    return False, self.errors
                
                # Data satırlarını validate et
                for idx, line in enumerate(lines[1:], start=2):
                    line = line.strip()
                    if not line:  # Boş satırları atla
                        continue
                    
                    self.validated_rows += 1
                    row_errors = self._validate_row(idx, line)
                    self.errors.extend(row_errors)
                
                return len(self.errors) == 0, self.errors
                
        except Exception as e:
            self.errors.append(CSVValidationError(
                row_number=0,
                error_type='HEADER',
                error_detail=f'Dosya okuma hatası: {str(e)}',
                raw_row=''
            ))
            return False, self.errors
    
    def validate_stream(self, stream, encoding='utf-8') -> Tuple[bool, List[CSVValidationError]]:
        """
        Validate CSV from a stream (file-like object).
        Works with S3 streams, local files, or any readable stream.
        
        Args:
            stream: File-like object (io.BytesIO, S3 Body, open file, etc.)
            encoding: Text encoding (default: utf-8)
        
        Returns:
            (is_valid, errors) tuple
        """
        self.errors = []
        self.validated_rows = 0
        
        try:
            # Wrap binary stream in TextIOWrapper if needed
            if isinstance(stream, (io.BytesIO, io.BufferedReader)) or hasattr(stream, 'read') and not hasattr(stream, 'readline'):
                # If it's a binary stream or boto3 StreamingBody, wrap it
                text_stream = io.TextIOWrapper(stream, encoding=encoding)
            else:
                # Already a text stream
                text_stream = stream
            
            # Read all lines
            lines = text_stream.readlines()
            
            if not lines:
                self.errors.append(CSVValidationError(
                    row_number=0,
                    error_type='HEADER',
                    error_detail='CSV dosyası boş',
                    raw_row=''
                ))
                return False, self.errors
            
            # Header kontrolü
            header_line = lines[0].strip()
            if not self._validate_header(header_line):
                self.errors.append(CSVValidationError(
                    row_number=1,
                    error_type='HEADER',
                    error_detail=f'Header beklenen formatta değil. Beklenen: {self.EXPECTED_HEADERS}',
                    raw_row=header_line
                ))
                return False, self.errors
            
            # Data satırlarını validate et
            for idx, line in enumerate(lines[1:], start=2):
                line = line.strip()
                if not line:  # Boş satırları atla
                    continue
                
                self.validated_rows += 1
                row_errors = self._validate_row(idx, line)
                self.errors.extend(row_errors)
            
            return len(self.errors) == 0, self.errors
            
        except Exception as e:
            self.errors.append(CSVValidationError(
                row_number=0,
                error_type='HEADER',
                error_detail=f'Stream okuma hatası: {str(e)}',
                raw_row=''
            ))
            return False, self.errors
    
    def _validate_header(self, header_line: str) -> bool:
        """1. Kural: CSV başlık kontrolü"""
        headers = [h.strip() for h in header_line.split(self.FIELD_DELIMITER)]
        return headers == self.EXPECTED_HEADERS
    
    def _validate_row(self, row_number: int, raw_row: str) -> List[CSVValidationError]:
        """Bir satırı tüm kurallara göre validate eder"""
        errors = []
        
        # 2. Kural: Alan ayracı kontrolü
        if self.FIELD_DELIMITER not in raw_row:
            errors.append(CSVValidationError(
                row_number=row_number,
                error_type='DELIMITER',
                error_detail=f'Alan ayracı "{self.FIELD_DELIMITER}" bulunamadı',
                raw_row=raw_row
            ))
            return errors  # Ayraç yoksa diğer kontrollere geçme
        
        # Satırı parse et
        fields = raw_row.split(self.FIELD_DELIMITER)
        
        # Kolon sayısı kontrolü
        if len(fields) != len(self.EXPECTED_HEADERS):
            errors.append(CSVValidationError(
                row_number=row_number,
                error_type='DELIMITER',
                error_detail=f'Beklenen {len(self.EXPECTED_HEADERS)} kolon, bulunan {len(fields)} kolon',
                raw_row=raw_row
            ))
            return errors  # Kolon sayısı yanlışsa diğer kontrollere geçme
        
        # Field'ları parse et
        row_data = {
            'roundId': fields[0].strip(),
            'gameId': fields[1].strip(),
            'createDate': fields[2].strip(),
            'updateDate': fields[3].strip(),
            'betAmount': fields[4].strip(),
            'winAmount': fields[5].strip(),
            'status': fields[6].strip(),
        }
        
        # 7. Kural: Boş değer kontrolü
        for field_name, field_value in row_data.items():
            if not field_value:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type='EMPTY_FIELD',
                    error_detail=f'"{field_name}" alanı boş',
                    raw_row=raw_row
                ))
        
        # Boş alan varsa diğer kontrollere geçme
        if errors:
            return errors
        
        # 4. Kural: Tarih formatı kontrolü
        for date_field in ['createDate', 'updateDate']:
            date_value = row_data[date_field]
            if not self._validate_date_format(date_value):
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type='DATE_FORMAT',
                    error_detail=f'"{date_field}" geçersiz tarih formatı. Beklenen: YYYY-MM-DD HH:MM:SS, Bulunan: {date_value}',
                    raw_row=raw_row
                ))
        
        # 3. Kural: Decimal ayracı kontrolü + 5. Kural: Sayısal değer kontrolü
        for amount_field in ['betAmount', 'winAmount']:
            amount_value = row_data[amount_field]
            
            # Nokta kullanımı kontrolü (hata)
            if '.' in amount_value:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type='DECIMAL',
                    error_detail=f'"{amount_field}" alanında nokta (.) kullanımı hatalı. Virgül (,) kullanılmalı',
                    raw_row=raw_row
                ))
            
            # Sayısal değer ve negatif kontrolü
            numeric_error = self._validate_numeric_value(amount_value, amount_field)
            if numeric_error:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type='NUMERIC',
                    error_detail=numeric_error,
                    raw_row=raw_row
                ))
        
        # 6. Kural: Status değeri kontrolü
        status_value = row_data['status'].lower()
        if status_value not in self.VALID_STATUSES:
            errors.append(CSVValidationError(
                row_number=row_number,
                error_type='STATUS',
                error_detail=f'Status değeri geçersiz. Beklenen: {self.VALID_STATUSES}, Bulunan: {row_data["status"]}',
                raw_row=raw_row
            ))
        
        return errors
    
    def _validate_date_format(self, date_str: str) -> bool:
        """Tarih formatını kontrol eder (YYYY-MM-DD HH:MM:SS)"""
        if not self.DATE_PATTERN.match(date_str):
            return False
        
        try:
            datetime.strptime(date_str, self.DATE_FORMAT)
            return True
        except ValueError:
            return False
    
    def _validate_numeric_value(self, value: str, field_name: str) -> Optional[str]:
        """
        Sayısal değeri kontrol eder.
        Virgül decimal ayracı olarak kabul edilir.
        Negatif değerleri reddeder.
        
        Returns:
            Hata mesajı (varsa), yoksa None
        """
        try:
            # Virgülü noktaya çevir ve parse et
            normalized_value = value.replace(',', '.')
            numeric_value = float(normalized_value)
            
            # Negatif değer kontrolü
            if numeric_value < 0:
                return f'"{field_name}" negatif değer içeriyor: {value}'
            
            return None
        except ValueError:
            return f'"{field_name}" sayısal bir değer değil: {value}'
    
    def get_error_summary(self) -> Dict[str, int]:
        """Hata tiplerinin özetini döndürür"""
        summary = {}
        for error in self.errors:
            summary[error.error_type] = summary.get(error.error_type, 0) + 1
        return summary
    
    def get_grouped_errors(self) -> Dict[str, Dict[str, Dict]]:
        """
        Hataları tip ve detaya göre gruplar (SmartMessageFormatter ile uyumlu).
        
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
        from collections import defaultdict
        
        grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "rows": []}))
        
        for error in self.errors:
            error_type = error.error_type
            # Hata detayını kısalt ve normalize et
            detail = self._simplify_error_detail(error.error_detail)
            
            grouped[error_type][detail]["count"] += 1
            grouped[error_type][detail]["rows"].append(error.row_number)
        
        # Satır numaralarını sırala
        for error_type in grouped:
            for detail in grouped[error_type]:
                grouped[error_type][detail]["rows"].sort()
        
        return dict(grouped)
    
    def _simplify_error_detail(self, detail: str) -> str:
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
