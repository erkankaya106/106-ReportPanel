import hmac
import hashlib
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import boto3
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Bayi, TransferLog

# ── Sabitler ──────────────────────────────────────────────────────────────────
MAX_ZIP_SIZE_MB = 100
MAX_CSV_FILES_PER_ZIP = 500          # provider × date × 3 dosya
TIMESTAMP_TOLERANCE_SECONDS = 300    # 5 dakika

# ZIP bomb koruması
MAX_UNCOMPRESSED_MB   = 500          # ZIP açıldığında toplam disk kullanımı
MAX_SINGLE_FILE_MB    = 50           # Tek dosya limiti
MAX_COMPRESSION_RATIO = 100          # Şüpheli sıkıştırma oranı eşiği
MAX_FILES_IN_ZIP      = 600          # ZIP içindeki maksimum dosya sayısı

# Her provider_id klasörü içinde bulunması zorunlu CSV dosya adları
REQUIRED_CSV_FILES = {"bet.csv", "win.csv", "canceled.csv"}

# Geçerli provider_id formatı (2 haneli sayı)
PROVIDER_ID_PATTERN = re.compile(r"^provider_id=(\d{2})$")

# Geçerli date klasör formatı: date=YYYY-MM-DD
DATE_FOLDER_PATTERN = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def sanitize_error_message(error_msg: str) -> str:
    """Hata mesajından secret_key gibi hassas bilgileri temizler."""
    if not error_msg:
        return error_msg
    sensitive_patterns = ["secret_key", "secret", "key", "password", "token"]
    sanitized = error_msg
    for pattern in sensitive_patterns:
        if pattern.lower() in sanitized.lower():
            sanitized = re.sub(
                rf"\b{re.escape(pattern)}\s*[:=]\s*[^\s,;)]+",
                f"{pattern}=[REDACTED]",
                sanitized,
                flags=re.IGNORECASE,
            )
    return sanitized


def validate_hmac(branch_id: str, secret_key: str, signature: str, message: str) -> bool:
    """Bayiden gelen imzayı doğrular."""
    expected_sig = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_sig, signature)


def validate_zip_filename(zip_filename: str, branch_id: str) -> tuple[bool, str]:
    """
    ZIP dosya adı formatını kontrol eder.
    Beklenen format: {branch_id}.zip  (örn: 41000.zip)

    Returns:
        (is_valid, error_message)
    """
    expected = f"{branch_id}.zip"
    if zip_filename != expected:
        return False, (
            f"ZIP dosya adı hatalı. Beklenen: {expected}, Gelen: {zip_filename}"
        )
    return True, ""


def validate_date_folder(date_str: str) -> tuple[bool, str]:
    """
    date=YYYY-MM-DD formatındaki tarihi doğrular.

    Args:
        date_str: Klasör adından çıkarılan YYYY-MM-DD string

    Returns:
        (is_valid, error_message)
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True, ""
    except ValueError:
        return False, f"Geçersiz tarih formatı: {date_str} (Beklenen: YYYY-MM-DD)"


def validate_csv_content(csv_path: Path, csv_type: str) -> tuple[bool, str]:
    """
    CSV dosyasının header'ını kontrol eder.
    csv_type: 'bet', 'win', 'canceled'

    Returns:
        (is_valid, error_message)
    """
    from .csv_validator import CSV_TYPE_CONFIG

    config = CSV_TYPE_CONFIG.get(csv_type)
    if config is None:
        return False, f"Bilinmeyen CSV tipi: {csv_type}"

    expected_headers = config["headers"]

    try:
        with csv_path.open("rb") as f:
            first_chunk = b""
            while b"\n" not in first_chunk:
                data = f.read(4096)
                if not data:
                    break
                first_chunk += data

        header_line = first_chunk.split(b"\n")[0].decode("utf-8", errors="ignore").strip()

        if not header_line:
            return False, f"{csv_path.name}: Dosya boş veya header satırı bulunamadı"

        headers = [h.strip() for h in header_line.split(";")]

        if headers != expected_headers:
            return False, (
                f"{csv_path.name}: Header hatalı. "
                f"Beklenen: {expected_headers}, Bulunan: {headers}"
            )

        return True, ""
    except Exception as e:
        return False, f"{csv_path.name}: Okuma hatası — {str(e)}"


def validate_hive_folder_structure(
    temp_dir: Path, branch_id: str
) -> tuple[bool, str, list[dict]]:
    """
    Çıkarılan ZIP içindeki Hive-partition klasör yapısını doğrular.

    Beklenen yapı:
        branch_id={branch_id}/
            provider_id={NN}/
                date={YYYY-MM-DD}/
                    bet.csv
                    win.csv
                    canceled.csv

    Returns:
        (is_valid, error_message, csv_entries)

    csv_entries her CSV için:
        { "path": Path, "csv_type": str, "provider_id": str, "date": str }
    """
    items = list(temp_dir.iterdir())

    if len(items) == 0:
        return False, "ZIP dosyası boş", []

    if len(items) > 1:
        return (
            False,
            "ZIP içinde tek bir kök klasör olmalı, birden fazla dosya/klasör bulundu",
            [],
        )

    root = items[0]

    if not root.is_dir():
        return False, "ZIP içinde klasör yerine dosya bulundu", []

    # Kök klasör adı kontrolü: branch_id=41000
    expected_root = f"branch_id={branch_id}"
    if root.name != expected_root:
        return (
            False,
            f"Kök klasör adı hatalı. Beklenen: {expected_root}, Bulunan: {root.name}",
            [],
        )

    # provider_id= alt klasörlerini tara
    provider_dirs = [p for p in root.iterdir() if p.is_dir()]

    if not provider_dirs:
        return False, f"{root.name}/ içinde provider_id= klasörü bulunamadı", []

    csv_entries = []

    for provider_dir in sorted(provider_dirs):
        # provider_id= formatı kontrolü
        match = PROVIDER_ID_PATTERN.match(provider_dir.name)
        if not match:
            return (
                False,
                f"Geçersiz provider klasörü adı: {provider_dir.name} "
                f"(Beklenen: provider_id=NN, örn: provider_id=01)",
                [],
            )
        provider_id = match.group(1)

        # date= alt klasörlerini tara
        date_dirs = [d for d in provider_dir.iterdir() if d.is_dir()]

        if not date_dirs:
            return (
                False,
                f"{provider_dir.name}/ içinde date= klasörü bulunamadı",
                [],
            )

        for date_dir in sorted(date_dirs):
            date_match = DATE_FOLDER_PATTERN.match(date_dir.name)
            if not date_match:
                return (
                    False,
                    f"Geçersiz date klasörü adı: {date_dir.name} "
                    f"(Beklenen: date=YYYY-MM-DD, örn: date=2026-02-26)",
                    [],
                )

            date_str = date_match.group(1)
            is_valid_date, date_error = validate_date_folder(date_str)
            if not is_valid_date:
                return False, date_error, []

            # bet.csv, win.csv, canceled.csv kontrolü
            found_files = {f.name for f in date_dir.iterdir() if f.is_file()}
            missing = REQUIRED_CSV_FILES - found_files
            if missing:
                return (
                    False,
                    f"{provider_dir.name}/{date_dir.name}/ içinde eksik dosya(lar): "
                    f"{sorted(missing)}",
                    [],
                )

            extra = {
                f for f in found_files if f not in REQUIRED_CSV_FILES and f.endswith(".csv")
            }
            if extra:
                return (
                    False,
                    f"{provider_dir.name}/{date_dir.name}/ içinde beklenmeyen dosya(lar): "
                    f"{sorted(extra)}",
                    [],
                )

            # Her CSV'yi listeye ekle
            for csv_name in sorted(REQUIRED_CSV_FILES):
                csv_type = csv_name.replace(".csv", "")  # bet / win / canceled
                csv_entries.append({
                    "path": date_dir / csv_name,
                    "csv_type": csv_type,
                    "provider_id": provider_id,
                    "date": date_str,
                })

    if len(csv_entries) > MAX_CSV_FILES_PER_ZIP:
        return (
            False,
            f"ZIP içinde çok fazla CSV dosyası ({len(csv_entries)}). "
            f"Maksimum: {MAX_CSV_FILES_PER_ZIP}",
            [],
        )

    return True, "", csv_entries


def extract_and_validate_zip(
    uploaded_file, branch_id: str
) -> tuple[bool, str, Path | None, str, list[dict]]:
    """
    ZIP dosyasını geçici dizine çıkarır ve Hive-partition yapısını doğrular.

    Returns:
        (is_valid, error_message, temp_dir, root_folder_name, csv_entries)
    """
    temp_dir = None

    try:
        # Dosya boyutu kontrolü
        file_size_mb = uploaded_file.size / (1024 * 1024)
        if file_size_mb > MAX_ZIP_SIZE_MB:
            return (
                False,
                f"ZIP dosyası çok büyük ({file_size_mb:.1f}MB). "
                f"Maksimum: {MAX_ZIP_SIZE_MB}MB",
                None, "", [],
            )

        # ZIP dosya adı kontrolü: {branch_id}.zip
        is_valid, error = validate_zip_filename(uploaded_file.name, branch_id)
        if not is_valid:
            return False, error, None, "", []

        # Geçici dizin oluştur
        temp_dir = Path(tempfile.mkdtemp(prefix="csv_upload_"))

        # ZIP'i diske kaydet
        temp_zip_path = temp_dir / "upload.zip"
        with temp_zip_path.open("wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # ZIP'i çıkar
        try:
            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                all_entries = zip_ref.infolist()

                # Dosya sayısı kontrolü (ZIP bomb)
                if len(all_entries) > MAX_FILES_IN_ZIP:
                    return (
                        False,
                        f"ZIP içinde çok fazla dosya ({len(all_entries)}). "
                        f"Maksimum: {MAX_FILES_IN_ZIP}",
                        temp_dir, "", [],
                    )

                total_uncompressed = 0
                for zip_info in all_entries:
                    name = zip_info.filename

                    # Path traversal koruması (geliştirilmiş)
                    if (
                        name.startswith("/")
                        or ".." in name
                        or "\\" in name
                        or "\x00" in name
                        or (len(name) > 1 and name[1] == ":")
                    ):
                        return (
                            False,
                            "Güvenlik hatası: ZIP içinde geçersiz dosya yolu",
                            temp_dir, "", [],
                        )

                    # ZIP bomb — tek dosya boyutu
                    if zip_info.file_size > MAX_SINGLE_FILE_MB * 1024 * 1024:
                        return (
                            False,
                            f"ZIP içinde tek dosya çok büyük ({zip_info.file_size // (1024*1024)} MB). "
                            f"Maksimum: {MAX_SINGLE_FILE_MB} MB",
                            temp_dir, "", [],
                        )

                    # ZIP bomb — toplam uncompressed boyut
                    total_uncompressed += zip_info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_MB * 1024 * 1024:
                        return (
                            False,
                            f"ZIP açık boyutu sınırı aşıyor. Maksimum: {MAX_UNCOMPRESSED_MB} MB",
                            temp_dir, "", [],
                        )

                    # ZIP bomb — şüpheli sıkıştırma oranı
                    if (
                        zip_info.compress_size > 0
                        and zip_info.file_size / zip_info.compress_size > MAX_COMPRESSION_RATIO
                    ):
                        return (
                            False,
                            f"ZIP içinde şüpheli sıkıştırma oranı tespit edildi: {zip_info.filename}",
                            temp_dir, "", [],
                        )

                zip_ref.extractall(temp_dir)
        except zipfile.BadZipFile:
            return False, "Geçersiz veya bozuk ZIP dosyası", temp_dir, "", []
        except Exception as e:
            return False, f"ZIP çıkarma hatası: {str(e)}", temp_dir, "", []

        temp_zip_path.unlink()

        # Hive-partition klasör yapısını doğrula
        is_valid, error, csv_entries = validate_hive_folder_structure(temp_dir, branch_id)
        if not is_valid:
            return False, error, temp_dir, "", []

        root_folder_name = f"branch_id={branch_id}"
        return True, "", temp_dir, root_folder_name, csv_entries

    except Exception as e:
        return False, f"ZIP işleme hatası: {str(e)}", temp_dir, "", []


def copy_csv_entries_to_storage(csv_entries: list[dict], branch_id: str):
    """
    CSV dosyalarını Hive-partition yapısıyla storage'a kopyalar.

    S3 hedef path:
        raw/branch_id={id}/provider_id={NN}/date={YYYY-MM-DD}/{bet|win|canceled}.csv

    Args:
        csv_entries: validate_hive_folder_structure'dan dönen liste
        branch_id: Bayi branch ID
    """
    if getattr(settings, "USE_LOCAL_FAKE_S3", False):
        base_dir = Path(
            getattr(settings, "LOCAL_S3_BASE_DIR", settings.BASE_DIR / "local_s3")
        )

        for entry in csv_entries:
            # raw/branch_id=41000/provider_id=01/date=2026-02-26/bet.csv
            target_path = (
                base_dir
                / "raw"
                / f"branch_id={branch_id}"
                / f"provider_id={entry['provider_id']}"
                / f"date={entry['date']}"
                / entry["path"].name
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry["path"], target_path)
    else:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

        for entry in csv_entries:
            s3_key = (
                f"raw/branch_id={branch_id}"
                f"/provider_id={entry['provider_id']}"
                f"/date={entry['date']}"
                f"/{entry['path'].name}"
            )
            with entry["path"].open("rb") as f:
                s3_client.upload_fileobj(
                    f,
                    settings.AWS_STORAGE_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={"ContentType": "text/csv"},
                )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@csrf_exempt
def mpi_raw_transactions_data(request):
    """
    ZIP dosyası yükleme endpoint'i.

    ZIP formatı:
        {branch_id}.zip
        └── branch_id={id}/
            └── provider_id={NN}/
                └── date={YYYY-MM-DD}/
                    ├── bet.csv
                    ├── win.csv
                    └── canceled.csv
    """
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Sadece POST desteklenir"}, status=405
        )

    # 1. Header verilerini al
    branch_id    = request.headers.get("X-Branch-ID")
    signature    = request.headers.get("X-Signature")
    timestamp    = request.headers.get("X-Timestamp")
    uploaded_file = request.FILES.get("file")

    # 2. Temel kontroller
    if not all([branch_id, signature, timestamp, uploaded_file]):
        return JsonResponse(
            {"status": "error", "message": "Eksik parametre"}, status=400
        )

    # 3. Bayi ve güvenlik doğrulama
    bayi = Bayi.objects.filter(branch_id=branch_id, is_active=True).first()
    if not bayi:
        return JsonResponse(
            {"status": "error", "message": "Geçersiz veya pasif bayi"}, status=403
        )

    # 4. ZIP uzantısı kontrolü
    if not uploaded_file.name.endswith(".zip"):
        return JsonResponse(
            {"status": "error", "message": "Sadece ZIP dosyası kabul edilir"}, status=400
        )

    # 5a. Timestamp replay attack koruması
    try:
        request_time = int(timestamp)
    except (ValueError, TypeError):
        return JsonResponse(
            {"status": "error", "message": "Geçersiz timestamp"}, status=400
        )

    if abs(int(time.time()) - request_time) > TIMESTAMP_TOLERANCE_SECONDS:
        return JsonResponse(
            {"status": "error", "message": "İstek süresi dolmuş"}, status=403
        )

    # 5b. Dosya SHA-256 hash'i hesapla (içerik imzalanıyor)
    sha256 = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        sha256.update(chunk)
    file_sha256 = sha256.hexdigest()
    uploaded_file.seek(0)  # Sonraki okumalar için dosya başına dön

    # 5c. HMAC imza kontrolü  (branch_id + zip_filename + timestamp + file_sha256)
    message = f"{branch_id}{uploaded_file.name}{timestamp}{file_sha256}"
    if not validate_hmac(branch_id, bayi.secret_key, signature, message):
        return JsonResponse(
            {"status": "error", "message": "Güvenlik doğrulaması başarısız"}, status=403
        )

    # 5d. Replay attack koruması — aynı imza 5 dk içinde tekrar gelirse reddet
    window_start = timezone.now() - timedelta(seconds=TIMESTAMP_TOLERANCE_SECONDS)
    if TransferLog.objects.filter(signature=signature, created_at__gte=window_start).exists():
        return JsonResponse(
            {"status": "error", "message": "Tekrarlanan istek reddedildi"}, status=409
        )

    # 6. PENDING log oluştur
    transfer_log = TransferLog.objects.create(
        bayi=bayi,
        filename=uploaded_file.name,
        status="PENDING",
        signature=signature,
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    temp_dir = None
    try:
        # 7. ZIP'i çıkar ve Hive-partition yapısını doğrula
        is_valid, error, temp_dir, root_folder_name, csv_entries = (
            extract_and_validate_zip(uploaded_file, branch_id)
        )

        if not is_valid:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            transfer_log.status = "FAILED"
            transfer_log.error_message = error
            transfer_log.save()
            return JsonResponse({"status": "error", "message": error}, status=400)

        # 8. Her CSV dosyasının header'ını doğrula
        validation_errors = []
        for entry in csv_entries:
            is_csv_valid, csv_error = validate_csv_content(entry["path"], entry["csv_type"])
            if not is_csv_valid:
                validation_errors.append(csv_error)

        if validation_errors:
            error_message = "CSV format hataları: " + "; ".join(validation_errors[:5])
            if len(validation_errors) > 5:
                error_message += f" (ve {len(validation_errors) - 5} hata daha)"

            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            transfer_log.status = "FAILED"
            transfer_log.error_message = error_message
            transfer_log.save()
            return JsonResponse({"status": "error", "message": error_message}, status=400)

        # 9. CSV'leri storage'a kopyala (raw/ prefix, Hive-partition)
        try:
            copy_csv_entries_to_storage(csv_entries, branch_id)
        except Exception as e:
            sanitized_error = sanitize_error_message(str(e))
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            transfer_log.status = "FAILED"
            transfer_log.error_message = f"Storage transfer hatası: {sanitized_error}"
            transfer_log.save()
            return JsonResponse(
                {"status": "error", "message": "Storage transfer hatası"}, status=500
            )

        # 10. Başarılı — log güncelle
        s3_path = f"raw/branch_id={branch_id}"
        transfer_log.status = "SUCCESS"
        transfer_log.s3_path = s3_path
        transfer_log.error_message = f"{len(csv_entries)} CSV dosyası yüklendi"
        transfer_log.save()

        # 11. Geçici dosyaları temizle
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        return JsonResponse(
            {
                "status": "success",
                "message": (
                    f"ZIP dosyası başarıyla yüklendi. "
                    f"{len(csv_entries)} CSV dosyası işlendi."
                ),
                "folder": root_folder_name,
                "csv_count": len(csv_entries),
            },
            status=200,
        )

    except Exception as e:
        sanitized_error = sanitize_error_message(str(e))
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        transfer_log.status = "FAILED"
        transfer_log.error_message = f"Beklenmeyen hata: {sanitized_error}"
        transfer_log.save()
        return JsonResponse(
            {"status": "error", "message": "İşlem sırasında hata oluştu"}, status=500
        )
