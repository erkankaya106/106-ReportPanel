"""
CSV Validator - CSV dosyalarındaki format hatalarını tespit eder.

Desteklenen 3 CSV tipi:
  bet.csv      → roundId;gameId;createDate;updateDate;betAmount;status
  win.csv      → roundId;gameId;createDate;updateDate;winAmount
  canceled.csv → roundId;gameId;createDate;updateDate;betAmount

Doğrulama kuralları (tipe göre uygulanır):
1. CSV Başlık Kontrolü
2. Alan Ayracı Kontrolü (;)
3. Decimal Ayracı Kontrolü (,)
4. Tarih Formatı Kontrolü (YYYY-MM-DD HH:MM:SS)
5. Sayısal Değer Kontrolü (negatif değer)
6. Status Değeri Kontrolü — sadece bet.csv: win | lost | pending | canceled
7. Boş Değer Kontrolü
"""

import io
from pathlib import Path
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple, BinaryIO


# CSV tipleri ve karşılık gelen header tanımları
CSV_TYPE_CONFIG = {
    "bet": {
        "headers": ["roundId", "gameId", "createDate", "updateDate", "betAmount", "status"],
        "amount_fields": ["betAmount"],
        "has_status": True,
        "valid_statuses": ["win", "lost", "pending", "canceled"],
    },
    "win": {
        "headers": ["roundId", "gameId", "createDate", "updateDate", "winAmount"],
        "amount_fields": ["winAmount"],
        "has_status": False,
        "valid_statuses": [],
    },
    "canceled": {
        "headers": ["roundId", "gameId", "createDate", "updateDate", "betAmount"],
        "amount_fields": ["betAmount"],
        "has_status": False,
        "valid_statuses": [],
    },
}

# Dosya adından CSV tipini çıkar
FILENAME_TO_TYPE = {
    "bet.csv": "bet",
    "win.csv": "win",
    "canceled.csv": "canceled",
}


def resolve_csv_type(csv_type: Optional[str] = None, filename: Optional[str] = None) -> Optional[str]:
    """
    csv_type veya filename'den CSV tipini çözer.
    Returns: 'bet', 'win', 'canceled' veya None (bilinmiyorsa)
    """
    if csv_type and csv_type in CSV_TYPE_CONFIG:
        return csv_type
    if filename:
        basename = Path(filename).name.lower()
        return FILENAME_TO_TYPE.get(basename)
    return None


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
    """CSV dosyalarını tipe göre validate eder (bet / win / canceled)"""

    # Beklenen alan ayracı
    FIELD_DELIMITER = ";"

    # Beklenen decimal ayracı
    DECIMAL_SEPARATOR = ","

    # Tarih formatı pattern
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def __init__(self, csv_type: Optional[str] = None):
        """
        Args:
            csv_type: 'bet', 'win' veya 'canceled'.
                      None verilirse validate metoduna geçilen filename'den otomatik belirlenir.
        """
        self._csv_type = csv_type
        self.errors: List[CSVValidationError] = []
        self.validated_rows = 0

    # ── Tip konfigürasyonu ────────────────────────────────────────────────────

    def _get_config(self) -> dict:
        """Aktif CSV tipinin konfigürasyonunu döner."""
        if self._csv_type and self._csv_type in CSV_TYPE_CONFIG:
            return CSV_TYPE_CONFIG[self._csv_type]
        # Tip bilinmiyorsa bet.csv varsayılanına dön (en katı kural seti)
        return CSV_TYPE_CONFIG["bet"]

    @property
    def EXPECTED_HEADERS(self) -> List[str]:
        return self._get_config()["headers"]

    # ── Public validate metodları ─────────────────────────────────────────────

    def validate_file_chunked(
        self, file_path: str, chunk_size: int = 1000
    ) -> Tuple[bool, List[CSVValidationError]]:
        """
        Bir CSV dosyasını ChunkedFileReader kullanarak memory-safe şekilde validate eder.
        csv_type belirlenmemişse file_path'teki dosya adından otomatik çıkarır.
        """
        from .queue_manager import ChunkedFileReader

        self._auto_detect_type(Path(file_path).name)
        self.errors = []
        self.validated_rows = 0

        reader = ChunkedFileReader(Path(file_path), chunk_size=chunk_size)

        try:
            header_validated = False

            for chunk, _ in reader.read_chunks():
                for line_number, line in chunk:
                    if line_number == 1:
                        if not self._validate_header(line):
                            self.errors.append(CSVValidationError(
                                row_number=1,
                                error_type="HEADER",
                                error_detail=(
                                    f"Header beklenen formatta değil. "
                                    f"Beklenen: {self.EXPECTED_HEADERS}"
                                ),
                                raw_row=line,
                            ))
                            return False, self.errors
                        header_validated = True
                        continue

                    if not line:
                        continue

                    self.validated_rows += 1
                    row_errors = self._validate_row(line_number, line)
                    self.errors.extend(row_errors)

            if not header_validated:
                self.errors.append(CSVValidationError(
                    row_number=0,
                    error_type="HEADER",
                    error_detail="CSV dosyası boş",
                    raw_row="",
                ))
                return False, self.errors

            return len(self.errors) == 0, self.errors

        except Exception as e:
            self.errors.append(CSVValidationError(
                row_number=0,
                error_type="HEADER",
                error_detail=f"Dosya okuma hatası: {str(e)}",
                raw_row="",
            ))
            return False, self.errors

    def validate_file(self, file_path: str) -> Tuple[bool, List[CSVValidationError]]:
        """
        Bir CSV dosyasını tamamen validate eder.
        csv_type belirlenmemişse file_path'teki dosya adından otomatik çıkarır.
        """
        self._auto_detect_type(Path(file_path).name)
        self.errors = []
        self.validated_rows = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                self.errors.append(CSVValidationError(
                    row_number=0,
                    error_type="HEADER",
                    error_detail="CSV dosyası boş",
                    raw_row="",
                ))
                return False, self.errors

            header_line = lines[0].strip()
            if not self._validate_header(header_line):
                self.errors.append(CSVValidationError(
                    row_number=1,
                    error_type="HEADER",
                    error_detail=(
                        f"Header beklenen formatta değil. Beklenen: {self.EXPECTED_HEADERS}"
                    ),
                    raw_row=header_line,
                ))
                return False, self.errors

            for idx, line in enumerate(lines[1:], start=2):
                line = line.strip()
                if not line:
                    continue
                self.validated_rows += 1
                row_errors = self._validate_row(idx, line)
                self.errors.extend(row_errors)

            return len(self.errors) == 0, self.errors

        except Exception as e:
            self.errors.append(CSVValidationError(
                row_number=0,
                error_type="HEADER",
                error_detail=f"Dosya okuma hatası: {str(e)}",
                raw_row="",
            ))
            return False, self.errors

    def validate_stream(
        self, stream, encoding: str = "utf-8"
    ) -> Tuple[bool, List[CSVValidationError]]:
        """
        Validate CSV from a stream (file-like object).
        Works with S3 streams, local files, or any readable stream.

        Args:
            stream: File-like object (io.BytesIO, S3 Body, open file, etc.)
            encoding: Text encoding (default: utf-8)
        """
        self.errors = []
        self.validated_rows = 0

        try:
            if hasattr(stream, "read"):
                content = stream.read()
                if isinstance(content, bytes):
                    content = content.decode(encoding)
                lines = content.splitlines()
            else:
                lines = list(stream)

            if not lines:
                self.errors.append(CSVValidationError(
                    row_number=0,
                    error_type="HEADER",
                    error_detail="CSV dosyası boş",
                    raw_row="",
                ))
                return False, self.errors

            header_line = lines[0].strip()
            if not self._validate_header(header_line):
                self.errors.append(CSVValidationError(
                    row_number=1,
                    error_type="HEADER",
                    error_detail=(
                        f"Header beklenen formatta değil. Beklenen: {self.EXPECTED_HEADERS}"
                    ),
                    raw_row=header_line,
                ))
                return False, self.errors

            for idx, line in enumerate(lines[1:], start=2):
                line = line.strip()
                if not line:
                    continue
                self.validated_rows += 1
                row_errors = self._validate_row(idx, line)
                self.errors.extend(row_errors)

            return len(self.errors) == 0, self.errors

        except Exception as e:
            self.errors.append(CSVValidationError(
                row_number=0,
                error_type="HEADER",
                error_detail=f"Stream okuma hatası: {str(e)}",
                raw_row="",
            ))
            return False, self.errors

    # ── İç yardımcı metodlar ─────────────────────────────────────────────────

    def _auto_detect_type(self, filename: str):
        """Eğer csv_type belirlenmemişse dosya adından otomatik belirler."""
        if not self._csv_type:
            detected = resolve_csv_type(filename=filename)
            if detected:
                self._csv_type = detected

    def _validate_header(self, header_line: str) -> bool:
        """1. Kural: CSV başlık kontrolü"""
        headers = [h.strip() for h in header_line.split(self.FIELD_DELIMITER)]
        return headers == self.EXPECTED_HEADERS

    def _validate_row(self, row_number: int, raw_row: str) -> List[CSVValidationError]:
        """Bir satırı tüm kurallara göre validate eder"""
        errors = []
        config = self._get_config()
        expected_headers = config["headers"]
        amount_fields = config["amount_fields"]
        has_status = config["has_status"]
        valid_statuses = config["valid_statuses"]

        # 2. Kural: Alan ayracı kontrolü
        if self.FIELD_DELIMITER not in raw_row:
            errors.append(CSVValidationError(
                row_number=row_number,
                error_type="DELIMITER",
                error_detail=f'Alan ayracı "{self.FIELD_DELIMITER}" bulunamadı',
                raw_row=raw_row,
            ))
            return errors

        fields = raw_row.split(self.FIELD_DELIMITER)

        if len(fields) != len(expected_headers):
            errors.append(CSVValidationError(
                row_number=row_number,
                error_type="DELIMITER",
                error_detail=(
                    f"Beklenen {len(expected_headers)} kolon, bulunan {len(fields)} kolon"
                ),
                raw_row=raw_row,
            ))
            return errors

        # Field'ları header isimleriyle eşleştir
        row_data = {header: fields[i].strip() for i, header in enumerate(expected_headers)}

        # 7. Kural: Boş değer kontrolü
        for field_name, field_value in row_data.items():
            if not field_value:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type="EMPTY_FIELD",
                    error_detail=f'"{field_name}" alanı boş',
                    raw_row=raw_row,
                ))

        if errors:
            return errors

        # 4. Kural: Tarih formatı kontrolü
        for date_field in ["createDate", "updateDate"]:
            date_value = row_data[date_field]
            if not self._validate_date_format(date_value):
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type="DATE_FORMAT",
                    error_detail=(
                        f'"{date_field}" geçersiz tarih formatı. '
                        f"Beklenen: YYYY-MM-DD HH:MM:SS, Bulunan: {date_value}"
                    ),
                    raw_row=raw_row,
                ))

        # 3. Kural: Decimal + 5. Kural: Sayısal değer kontrolü
        for amount_field in amount_fields:
            amount_value = row_data[amount_field]

            if "." in amount_value:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type="DECIMAL",
                    error_detail=(
                        f'"{amount_field}" alanında nokta (.) kullanımı hatalı. '
                        f"Virgül (,) kullanılmalı"
                    ),
                    raw_row=raw_row,
                ))

            numeric_error = self._validate_numeric_value(amount_value, amount_field)
            if numeric_error:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type="NUMERIC",
                    error_detail=numeric_error,
                    raw_row=raw_row,
                ))

        # 6. Kural: Status değeri kontrolü (sadece bet.csv)
        if has_status:
            status_value = row_data.get("status", "").lower()
            if status_value not in valid_statuses:
                errors.append(CSVValidationError(
                    row_number=row_number,
                    error_type="STATUS",
                    error_detail=(
                        f"Status değeri geçersiz. "
                        f"Beklenen: {valid_statuses}, Bulunan: {row_data.get('status', '')}"
                    ),
                    raw_row=raw_row,
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
        """
        try:
            normalized_value = value.replace(",", ".")
            numeric_value = float(normalized_value)
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
        """
        from collections import defaultdict

        grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "rows": []}))

        for error in self.errors:
            error_type = error.error_type
            detail = self._simplify_error_detail(error.error_detail)
            grouped[error_type][detail]["count"] += 1
            grouped[error_type][detail]["rows"].append(error.row_number)

        for error_type in grouped:
            for detail in grouped[error_type]:
                grouped[error_type][detail]["rows"].sort()

        return dict(grouped)

    def _simplify_error_detail(self, detail: str) -> str:
        """Hata detayını kısaltır ve sadeleştirir"""
        detail = detail.replace("ı", "i").replace("ş", "s").replace("ğ", "g")
        detail = detail.replace("ü", "u").replace("ö", "o").replace("ç", "c")
        detail = detail.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
        detail = detail.replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")

        if len(detail) > 80:
            detail = detail[:77] + "..."

        return detail
