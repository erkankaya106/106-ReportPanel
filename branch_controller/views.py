import hmac
import hashlib
import tempfile
import zipfile
import shutil
import re
from datetime import datetime
from pathlib import Path

import boto3
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Bayi, TransferLog

# Configuration constants
MAX_ZIP_SIZE_MB = 100
MAX_CSV_FILES_PER_ZIP = 100

def sanitize_error_message(error_msg: str) -> str:
    """
    Hata mesajından secret_key gibi hassas bilgileri temizler.
    """
    if not error_msg:
        return error_msg
    
    # secret_key kelimesini ve benzer hassas bilgileri temizle
    sensitive_patterns = ['secret_key', 'secret', 'key', 'password', 'token']
    sanitized = error_msg
    
    # Basit bir yaklaşım: secret_key geçiyorsa [REDACTED] yaz
    for pattern in sensitive_patterns:
        if pattern.lower() in sanitized.lower():
            # Eğer tam olarak secret_key geçiyorsa, o kısmı [REDACTED] ile değiştir
            import re
            sanitized = re.sub(
                rf'\b{re.escape(pattern)}\s*[:=]\s*[^\s,;)]+',
                f'{pattern}=[REDACTED]',
                sanitized,
                flags=re.IGNORECASE
            )
    
    return sanitized


def validate_hmac(branch_id, secret_key, signature, message):
    """Bayiden gelen imzayı doğrular."""
    expected_sig = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_sig, signature)


def validate_csv_format(uploaded_file) -> tuple[bool, str]:
    """
    CSV dosyasının formatını kontrol eder.
    Beklenen format: roundId;gameId;createDate;updateDate;betAmount;winAmount;status
    Returns: (is_valid, error_message)
    """
    EXPECTED_HEADERS = ['roundId', 'gameId', 'createDate', 'updateDate', 'betAmount', 'winAmount', 'status']
    
    try:
        # İlk satırı oku (header)
        first_chunk = b''
        for chunk in uploaded_file.chunks():
            first_chunk += chunk
            if b'\n' in first_chunk:
                break
        
        # Header satırını parse et
        header_line = first_chunk.split(b'\n')[0].decode('utf-8', errors='ignore').strip()
        if not header_line:
            return False, "CSV dosyası boş veya header satırı bulunamadı"
        
        headers = [h.strip() for h in header_line.split(';')]
        
        # Kolon sayısı kontrolü
        if len(headers) != len(EXPECTED_HEADERS):
            return False, f"Beklenen {len(EXPECTED_HEADERS)} kolon, bulunan {len(headers)} kolon"
        
        # Header'ların sırası ve isimleri kontrolü
        if headers != EXPECTED_HEADERS:
            return False, f"Header'lar beklenen formatta değil. Beklenen: {EXPECTED_HEADERS}, Bulunan: {headers}"
        
        return True, ""
    except Exception as e:
        return False, f"CSV format kontrolü hatası: {str(e)}"


def parse_ddmmyyyy_date(date_str: str) -> tuple[bool, str, str]:
    """
    DDMMYYYY formatındaki tarihi parse eder.
    Args:
        date_str: 8 haneli tarih string (örn: "03022026")
    Returns:
        (is_valid, error_message, iso_date_str)
    """
    if len(date_str) != 8 or not date_str.isdigit():
        return False, "Tarih 8 haneli sayı olmalıdır (DDMMYYYY)", ""
    
    try:
        day = int(date_str[0:2])
        month = int(date_str[2:4])
        year = int(date_str[4:8])
        
        # Tarihi doğrula
        date_obj = datetime(year, month, day)
        iso_date = date_obj.strftime('%Y-%m-%d')
        
        return True, "", iso_date
    except ValueError as e:
        return False, f"Geçersiz tarih: {date_str}", ""


def validate_zip_filename(zip_filename: str, branch_id: str) -> tuple[bool, str, str]:
    """
    ZIP dosya adı formatını kontrol eder ve tarihi çıkarır.
    Format: branch_{branch_id}_{DDMMYYYY}.zip
    
    Args:
        zip_filename: ZIP dosyasının adı
        branch_id: Bayi branch ID
    
    Returns:
        (is_valid, error_message, date_str_ddmmyyyy)
    """
    # Pattern: branch_10000_03022026.zip
    pattern = rf'^branch_(\d+)_(\d{{8}})\.zip$'
    match = re.match(pattern, zip_filename)
    
    if not match:
        return False, f"ZIP dosya adı formatı hatalı. Beklenen: branch_{branch_id}_DDMMYYYY.zip", ""
    
    file_branch_id = match.group(1)
    date_str = match.group(2)
    
    # Branch ID kontrolü
    if file_branch_id != branch_id:
        return False, f"ZIP dosya adındaki branch ID ({file_branch_id}) eşleşmiyor", ""
    
    # Tarih formatını kontrol et
    is_valid_date, date_error, _ = parse_ddmmyyyy_date(date_str)
    if not is_valid_date:
        return False, f"ZIP dosya adındaki tarih geçersiz: {date_error}", ""
    
    return True, "", date_str


def validate_csv_filename(csv_filename: str, branch_id: str, expected_date: str) -> tuple[bool, str]:
    """
    CSV dosya adı formatını kontrol eder.
    Format: branch_{branch_id}_{NN}_{DDMMYYYY}.csv
    
    Args:
        csv_filename: CSV dosyasının adı
        branch_id: Bayi branch ID
        expected_date: Beklenen tarih (DDMMYYYY formatında)
    
    Returns:
        (is_valid, error_message)
    """
    # Pattern: branch_10000_01_03022026.csv
    pattern = rf'^branch_(\d+)_(\d{{2}})_(\d{{8}})\.csv$'
    match = re.match(pattern, csv_filename)
    
    if not match:
        return False, f"CSV dosya adı formatı hatalı: {csv_filename}. Beklenen: branch_{branch_id}_NN_DDMMYYYY.csv"
    
    file_branch_id = match.group(1)
    sequence_num = match.group(2)
    date_str = match.group(3)
    
    # Branch ID kontrolü
    if file_branch_id != branch_id:
        return False, f"CSV dosya adındaki branch ID ({file_branch_id}) eşleşmiyor: {csv_filename}"
    
    # Sıra numarası kontrolü (01-99)
    try:
        seq = int(sequence_num)
        if seq < 1 or seq > 99:
            return False, f"Sıra numarası 01-99 arasında olmalı: {csv_filename}"
    except ValueError:
        return False, f"Geçersiz sıra numarası: {csv_filename}"
    
    # Tarih kontrolü
    if date_str != expected_date:
        return False, f"CSV tarih ({date_str}) klasör tarihi ({expected_date}) ile eşleşmiyor: {csv_filename}"
    
    # Tarih formatını doğrula
    is_valid_date, date_error, _ = parse_ddmmyyyy_date(date_str)
    if not is_valid_date:
        return False, f"CSV dosya adındaki tarih geçersiz ({csv_filename}): {date_error}"
    
    return True, ""


def validate_folder_structure(temp_dir: Path, expected_folder_name: str, branch_id: str, folder_date: str) -> tuple[bool, str, list]:
    """
    Çıkarılan ZIP içindeki klasör yapısını ve CSV dosyalarını kontrol eder.
    
    Args:
        temp_dir: ZIP'in çıkarıldığı geçici dizin
        expected_folder_name: Beklenen klasör adı (örn: branch_10000_03022026)
        branch_id: Bayi branch ID
        folder_date: Klasör tarihi (DDMMYYYY formatında)
    
    Returns:
        (is_valid, error_message, csv_files_list)
    """
    # Temp dizindeki içeriği kontrol et
    items = list(temp_dir.iterdir())
    
    if len(items) == 0:
        return False, "ZIP dosyası boş", []
    
    if len(items) > 1:
        return False, "ZIP içinde tek bir klasör olmalı, birden fazla dosya/klasör bulundu", []
    
    folder = items[0]
    
    if not folder.is_dir():
        return False, "ZIP içinde klasör yerine dosya bulundu", []
    
    # Klasör adı kontrolü
    if folder.name != expected_folder_name:
        return False, f"Klasör adı hatalı. Beklenen: {expected_folder_name}, Bulunan: {folder.name}", []
    
    # Klasör içindeki CSV dosyalarını bul
    csv_files = list(folder.glob('*.csv'))
    
    if len(csv_files) == 0:
        return False, f"Klasör içinde CSV dosyası bulunamadı: {folder.name}", []
    
    if len(csv_files) > MAX_CSV_FILES_PER_ZIP:
        return False, f"Klasör içinde çok fazla CSV dosyası ({len(csv_files)}). Maksimum: {MAX_CSV_FILES_PER_ZIP}", []
    
    # Her CSV dosyasının adını kontrol et
    for csv_file in csv_files:
        is_valid, error = validate_csv_filename(csv_file.name, branch_id, folder_date)
        if not is_valid:
            return False, error, []
    
    return True, "", csv_files


def extract_and_validate_zip(uploaded_file, branch_id: str) -> tuple[bool, str, Path, str, list]:
    """
    ZIP dosyasını geçici dizine çıkarır ve içeriğini doğrular.
    
    Args:
        uploaded_file: Yüklenen ZIP dosyası
        branch_id: Bayi branch ID
    
    Returns:
        (is_valid, error_message, temp_dir, folder_name, csv_files)
    """
    temp_dir = None
    
    try:
        # Dosya boyutu kontrolü
        file_size_mb = uploaded_file.size / (1024 * 1024)
        if file_size_mb > MAX_ZIP_SIZE_MB:
            return False, f"ZIP dosyası çok büyük ({file_size_mb:.1f}MB). Maksimum: {MAX_ZIP_SIZE_MB}MB", None, "", []
        
        # ZIP dosya adı kontrolü
        is_valid, error, date_str = validate_zip_filename(uploaded_file.name, branch_id)
        if not is_valid:
            return False, error, None, "", []
        
        # Beklenen klasör adı (ZIP adından .zip uzantısını çıkar)
        expected_folder_name = uploaded_file.name[:-4]  # branch_10000_03022026
        
        # Geçici dizin oluştur
        temp_dir = Path(tempfile.mkdtemp(prefix='csv_upload_'))
        
        # ZIP'i geçici bir dosyaya kaydet
        temp_zip_path = temp_dir / 'upload.zip'
        with temp_zip_path.open('wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)
        
        # ZIP dosyasını çıkar
        try:
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                # ZIP'in güvenli olup olmadığını kontrol et
                for zip_info in zip_ref.infolist():
                    # Path traversal saldırılarına karşı koruma
                    if zip_info.filename.startswith('/') or '..' in zip_info.filename:
                        return False, "Güvenlik hatası: ZIP içinde geçersiz dosya yolu", temp_dir, "", []
                
                zip_ref.extractall(temp_dir)
        except zipfile.BadZipFile:
            return False, "Geçersiz veya bozuk ZIP dosyası", temp_dir, "", []
        except Exception as e:
            return False, f"ZIP çıkarma hatası: {str(e)}", temp_dir, "", []
        
        # Geçici ZIP dosyasını sil
        temp_zip_path.unlink()
        
        # Klasör yapısını doğrula
        is_valid, error, csv_files = validate_folder_structure(temp_dir, expected_folder_name, branch_id, date_str)
        if not is_valid:
            return False, error, temp_dir, "", []
        
        return True, "", temp_dir, expected_folder_name, csv_files
        
    except Exception as e:
        return False, f"ZIP işleme hatası: {str(e)}", temp_dir, "", []


def copy_folder_to_storage(source_folder: Path, s3_key_prefix: str):
    """
    Çıkarılan klasörü storage'a kopyalar (S3 veya local fake S3).
    
    Args:
        source_folder: Kaynak klasör path
        s3_key_prefix: S3 key prefix (örn: "uploads/10000")
    """
    if getattr(settings, "USE_LOCAL_FAKE_S3", False):
        # Lokal fake S3
        base_dir = getattr(settings, "LOCAL_S3_BASE_DIR", settings.BASE_DIR / "local_s3")
        target_path = Path(base_dir) / s3_key_prefix / source_folder.name
        
        # Hedef dizin varsa sil (üzerine yaz)
        if target_path.exists():
            shutil.rmtree(target_path)
        
        # Klasörü kopyala
        shutil.copytree(source_folder, target_path)
    else:
        # Gerçek S3
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        
        # Klasör içindeki her dosyayı S3'e yükle
        for csv_file in source_folder.glob('*.csv'):
            s3_key = f"{s3_key_prefix}/{source_folder.name}/{csv_file.name}"
            
            with csv_file.open('rb') as f:
                s3_client.upload_fileobj(
                    f,
                    settings.AWS_STORAGE_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={'ContentType': 'text/csv'}
                )


def upload_to_storage(uploaded_file, s3_key: str):
    """Ortama göre dosyayı ya gerçek S3'e ya da lokal diske yazar."""
    if getattr(settings, "USE_LOCAL_FAKE_S3", False):
        # Lokal fake S3: BASE_DIR/local_s3/uploads/...
        base_dir = getattr(settings, "LOCAL_S3_BASE_DIR", settings.BASE_DIR / "local_s3")
        target_path = Path(base_dir) / s3_key  # örn: uploads/{branch_id}/{filename}
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Django UploadedFile üzerinde chunks() kullanarak diske yaz
        with target_path.open("wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)
    else:
        # GERÇEK S3 (eski kod burada; gerekirse yorumdan çıkarıp doğrudan kullanabilirsin)
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        s3_client.upload_fileobj(
            uploaded_file,
            settings.AWS_STORAGE_BUCKET_NAME,
            s3_key,
            ExtraArgs={"ContentType": uploaded_file.content_type},
        )

        # Eski doğrudan S3 upload kodu (referans için saklandı):
        # s3_client = boto3.client('s3')
        # s3_client.upload_fileobj(
        #     uploaded_file,
        #     settings.AWS_STORAGE_BUCKET_NAME,
        #     s3_key,
        #     ExtraArgs={'ContentType': uploaded_file.content_type}
        # )

@csrf_exempt
def enterprise_upload(request):
    """
    ZIP dosyası yükleme endpoint'i.
    ZIP içinde branch_{branch_id}_{DDMMYYYY} klasörü ve CSV dosyaları olmalı.
    """
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Sadece POST desteklenir"}, status=405)

    # 1. Header Verilerini Al
    branch_id = request.headers.get('X-Branch-ID')
    signature = request.headers.get('X-Signature')
    timestamp = request.headers.get('X-Timestamp')
    uploaded_file = request.FILES.get('file')

    # 2. Temel Kontroller
    if not all([branch_id, signature, timestamp, uploaded_file]):
        return JsonResponse({"status": "error", "message": "Eksik parametre"}, status=400)

    # 3. Bayi ve Güvenlik Doğrulama
    bayi = Bayi.objects.filter(branch_id=branch_id, is_active=True).first()
    if not bayi:
        return JsonResponse({"status": "error", "message": "Geçersiz veya pasif bayi"}, status=403)

    # 4. ZIP dosya kontrolü
    if not uploaded_file.name.endswith('.zip'):
        return JsonResponse({"status": "error", "message": "Sadece ZIP dosyası kabul edilir"}, status=400)

    # 5. İmzayı kontrol et (branch_id + zip_filename + timestamp)
    message = f"{branch_id}{uploaded_file.name}{timestamp}"
    if not validate_hmac(branch_id, bayi.secret_key, signature, message):
        return JsonResponse({"status": "error", "message": "Güvenlik doğrulaması başarısız"}, status=403)

    # 6. ZIP'i çıkar ve içeriğini doğrula
    temp_dir = None
    try:
        is_valid, error, temp_dir, folder_name, csv_files = extract_and_validate_zip(uploaded_file, branch_id)
        
        if not is_valid:
            # Hata durumunda geçici dosyaları temizle
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            TransferLog.objects.create(
                bayi=bayi,
                filename=uploaded_file.name,
                status="FAILED",
                error_message=error,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return JsonResponse({"status": "error", "message": error}, status=400)

        # 7. Her CSV dosyasının içeriğini doğrula
        validation_errors = []
        for csv_file in csv_files:
            # CSV dosyasını aç ve formatını kontrol et
            try:
                with csv_file.open('rb') as f:
                    # Django UploadedFile benzeri bir wrapper oluştur
                    class FileWrapper:
                        def __init__(self, file_obj):
                            self.file = file_obj
                            self.name = csv_file.name
                        
                        def chunks(self, chunk_size=8192):
                            while True:
                                data = self.file.read(chunk_size)
                                if not data:
                                    break
                                yield data
                        
                        def seek(self, pos):
                            self.file.seek(pos)
                    
                    wrapper = FileWrapper(f)
                    is_csv_valid, csv_error = validate_csv_format(wrapper)
                    
                    if not is_csv_valid:
                        validation_errors.append(f"{csv_file.name}: {csv_error}")
            except Exception as e:
                validation_errors.append(f"{csv_file.name}: Okuma hatası - {str(e)}")
        
        # Eğer CSV validasyon hataları varsa
        if validation_errors:
            error_message = "CSV format hataları: " + "; ".join(validation_errors[:5])  # İlk 5 hatayı göster
            if len(validation_errors) > 5:
                error_message += f" (ve {len(validation_errors)-5} hata daha)"
            
            # Geçici dosyaları temizle
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            TransferLog.objects.create(
                bayi=bayi,
                filename=uploaded_file.name,
                status="FAILED",
                error_message=error_message,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return JsonResponse({"status": "error", "message": error_message}, status=400)

        # 8. Klasörü storage'a kopyala
        s3_key_prefix = f"uploads/{branch_id}"
        folder_path = temp_dir / folder_name
        
        try:
            copy_folder_to_storage(folder_path, s3_key_prefix)
        except Exception as e:
            # Storage hatası
            sanitized_error = sanitize_error_message(str(e))
            
            # Geçici dosyaları temizle
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            TransferLog.objects.create(
                bayi=bayi,
                filename=uploaded_file.name,
                status="FAILED",
                error_message=f"Storage transfer hatası: {sanitized_error}",
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return JsonResponse({"status": "error", "message": "Storage transfer hatası"}, status=500)

        # 9. Başarılı - Log kaydet
        s3_path = f"{s3_key_prefix}/{folder_name}"
        TransferLog.objects.create(
            bayi=bayi,
            filename=uploaded_file.name,
            s3_path=s3_path,
            status="SUCCESS",
            error_message=f"{len(csv_files)} CSV dosyası yüklendi",
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        # 10. Geçici dosyaları temizle
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        return JsonResponse(
            {
                "status": "success",
                "message": f"ZIP dosyası başarıyla yüklendi. {len(csv_files)} CSV dosyası işlendi.",
                "folder": folder_name,
                "csv_count": len(csv_files)
            },
            status=200,
        )

    except Exception as e:
        # Beklenmeyen hata
        sanitized_error = sanitize_error_message(str(e))
        
        # Geçici dosyaları temizle
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        TransferLog.objects.create(
            bayi=bayi,
            filename=uploaded_file.name,
            status="FAILED",
            error_message=f"Beklenmeyen hata: {sanitized_error}",
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"status": "error", "message": "İşlem sırasında hata oluştu"}, status=500)