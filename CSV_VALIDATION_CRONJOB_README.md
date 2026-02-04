# CSV Validation Cronjob Sistemi

## Genel Bakış

Bu sistem, her gün saat 09:00'da otomatik olarak çalışan bir cronjob ile dün tarihli CSV dosyalarını satır satır analiz eder ve format hatalarını tespit eder. Sistem, sunucuyu yormadan işlem yapabilmek için custom Python kuyruk yapısı kullanır.

## Mimari

```
Cron (09:00) → Management Command → Queue Manager → Worker Threads → CSV Validator
                                                                           ↓
                                                           Hata Bulundu? → DB + Log
```

## Özellikler

### 1. Performans Koruyucu Kuyruk Sistemi
- Custom Python Thread + Queue yapısı
- Configurable worker thread sayısı (default: 4)
- Memory-safe chunk processing
- Graceful shutdown mekanizması
- Progress tracking

### 2. 7 Ana Kontrol Kuralı

1. **CSV Başlık Kontrolü**
   - Beklenen kolonlar: `roundId`, `gameId`, `createDate`, `updateDate`, `betAmount`, `winAmount`, `status`
   - Eksik veya fazla kolonlar tespit edilir

2. **Alan Ayracı Kontrolü**
   - Alan ayracı: `;` (noktalı virgül) olmalı
   - Yanlış ayraç kullanımı tespit edilir

3. **Decimal Ayracı Kontrolü**
   - Decimal ayracı: `,` (virgül) olmalı
   - Nokta (`.`) kullanımı hata olarak işaretlenir

4. **Tarih Formatı Kontrolü**
   - Format: `YYYY-MM-DD HH:MM:SS`
   - Geçersiz tarih formatları tespit edilir

5. **Sayısal Değer Kontrolü**
   - `betAmount` ve `winAmount` sayısal olmalı
   - Negatif değerler hata olarak işaretlenir

6. **Status Değeri Kontrolü**
   - Status sadece `won` veya `lost` olabilir (küçük harf)
   - Diğer değerler hata olarak işaretlenir

7. **Boş Değer Kontrolü**
   - Tüm zorunlu alanların dolu olması kontrol edilir

### 3. Dual Logging Sistemi
- **PostgreSQL Database**: `CSVValidationError` modelinde kalıcı kayıt
- **JSON Log Dosyası**: `logs/csv_validation_{tarih}.json` günlük log dosyaları

## Kurulum

### 1. Bağımlılıkları Yükleyin

```bash
pip install -r requirements.txt
```

### 2. Migration'ları Çalıştırın

```bash
python manage.py migrate
```

### 3. Zamanlanmış Görev Ayarla

#### Linux/Mac için (Crontab):

```bash
python manage.py crontab add
```

Crontab'ları listelemek için:

```bash
python manage.py crontab show
```

Crontab'ları kaldırmak için:

```bash
python manage.py crontab remove
```

#### Windows için (Task Scheduler):

**NOT**: django-crontab Windows'ta çalışmaz (`fcntl` modülü eksikliği). Windows'ta Task Scheduler kullanın.

**PowerShell ile Task Scheduler Oluşturma:**

```powershell
# Task Scheduler'da yeni görev oluştur
$action = New-ScheduledTaskAction -Execute "C:\Users\erkan.kaya\Desktop\106-ReportPanel\venv\Scripts\python.exe" -Argument "C:\Users\erkan.kaya\Desktop\106-ReportPanel\manage.py validate_yesterday_csvs" -WorkingDirectory "C:\Users\erkan.kaya\Desktop\106-ReportPanel"

$trigger = New-ScheduledTaskTrigger -Daily -At 09:00AM

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "CSV_Validation_Daily" -Action $action -Trigger $trigger -Settings $settings -Description "Her gün 09:00'da CSV dosyalarını validate eder"
```

**Task'ı Listele:**

```powershell
Get-ScheduledTask -TaskName "CSV_Validation_Daily"
```

**Task'ı Kaldır:**

```powershell
Unregister-ScheduledTask -TaskName "CSV_Validation_Daily" -Confirm:$false
```

**Manuel Çalıştır:**

```powershell
Start-ScheduledTask -TaskName "CSV_Validation_Daily"
```

## Kullanım

### Manuel Çalıştırma

```bash
# Dün tarihli CSV'leri kontrol et
python manage.py validate_yesterday_csvs

# Belirli bir tarih için kontrol et
python manage.py validate_yesterday_csvs --date=2026-02-02

# Dry-run (sadece rapor, DB'ye yazma)
python manage.py validate_yesterday_csvs --dry-run

# Worker sayısını ayarla
python manage.py validate_yesterday_csvs --workers=8

# Sadece belirli bir branch_id için
python manage.py validate_yesterday_csvs --branch-id=10000
```

### Otomatik Çalışma (Cronjob)

Sistem her gün saat 09:00'da otomatik olarak çalışır ve dün tarihli CSV'leri kontrol eder.

## Klasör Yapısı

CSV dosyaları şu yapıda saklanmalıdır:

```
local_s3/uploads/
├── {branch_id}/
│   ├── {tarih}/
│   │   ├── dosya1.csv
│   │   ├── dosya2.csv
│   │   └── ...
```

Örnek:
```
local_s3/uploads/
├── 10000/
│   ├── 2026-02-02/
│   │   └── branch_10000_test_20260202.csv
```

## Çıktı Formatı

### Console Output

```
======================================================================
CSV Validation Cronjob
======================================================================
Tarih: 2026-02-02
Worker Sayisi: 4
Dry Run: Hayir
======================================================================
[OK] 1 CSV dosyasi bulundu, isleme baslaniyor...
[QueueManager] 4 worker thread baslatildi

Islemler devam ediyor...
[HATA] branch_10000_test_20260202.csv: 8 satir, 5 hata
[QueueManager] Tum islemler tamamlandi

======================================================================
ISLEM TAMAMLANDI
======================================================================

OZET ISTATISTIKLER:
  - Taranan Dosya: 1
  - Islenen Dosya: 1
  - Toplam Satir: 8
  - Bulunan Hata: 5
  - Islem Suresi: 0.18 saniye
  - Islem Hizi: 44.1 satir/saniye

HATA TIPLERI:
  - DECIMAL: 1
  - NUMERIC: 1
  - STATUS: 1
  - EMPTY_FIELD: 1
  - DATE_FORMAT: 1

Log Dosyasi: C:\...\logs\csv_validation_2026-02-03.json

[OK] Hatalar veritabanina kaydedildi.
======================================================================
```

### JSON Log Dosyası

Her hata için ayrı satır:

```json
{
  "session_id": "20260203_110005",
  "timestamp": "2026-02-03T11:00:05.358685",
  "filename": "branch_10000_test_20260202.csv",
  "branch_id": "10000",
  "row_number": 4,
  "error_type": "DECIMAL",
  "error_detail": "\"betAmount\" alanında nokta (.) kullanımı hatalı. Virgül (,) kullanılmalı",
  "raw_row": "R003;G003;2026-02-02 10:02:00;2026-02-02 10:02:05;75.50;150,00;won"
}
```

Session özeti:

```json
{
  "session_id": "20260203_110005",
  "timestamp": "2026-02-03T11:00:05.365617",
  "type": "session_summary",
  "session_start": "2026-02-03T11:00:05.187140",
  "session_end": "2026-02-03T11:00:05.365617",
  "total_files": 1,
  "processed_files": 1,
  "total_rows": 8,
  "total_errors": 5,
  "error_summary": {
    "DECIMAL": 1,
    "NUMERIC": 1,
    "STATUS": 1,
    "EMPTY_FIELD": 1,
    "DATE_FORMAT": 1
  },
  "processing_time_seconds": 0.18,
  "rows_per_second": 44.08
}
```

## Django Admin

Hatalar Django Admin panelinde görüntülenebilir:

- URL: `/admin/branch_controller/csvvalidationerror/`
- Filtreleme: Hata tipi, Bayi, Tarih
- Arama: Dosya adı, Hata detayı

## Performans

- **Default Worker Sayısı**: 4 thread
- **Ortalama İşlem Hızı**: ~40-50 satır/saniye (sistem performansına bağlı)
- **Memory-Safe**: Büyük dosyalar chunk'lara bölünerek işlenir
- **Graceful Shutdown**: Ctrl+C ile güvenli durdurma

## Güvenlik

- Path traversal koruması
- Sadece belirlenmiş klasörlere erişim
- Timeout mekanizması (stuck job prevention)
- Log dosyalarında hassas bilgi sanitizasyonu

## Hata Ayıklama

### Crontab Logları

```bash
# Linux/Mac
tail -f /tmp/csv_validation_cron.log

# Windows - Manuel kontrol
python manage.py validate_yesterday_csvs --date=2026-02-02
```

### Veritabanı Sorguları

```python
from branch_controller.models import CSVValidationError

# Son 24 saatteki hatalar
from datetime import datetime, timedelta
yesterday = datetime.now() - timedelta(days=1)
errors = CSVValidationError.objects.filter(detected_at__gte=yesterday)

# Hata tipine göre grupla
from django.db.models import Count
error_summary = CSVValidationError.objects.values('error_type').annotate(count=Count('id'))
```

## Yapılandırma

### settings.py

```python
# Cronjob ayarları
CRONJOBS = [
    ('0 9 * * *', 'django.core.management.call_command', ['validate_yesterday_csvs']),
]

CRONTAB_LOCK_JOBS = True  # Aynı anda aynı job'ın çalışmasını engelle
CRONTAB_COMMAND_SUFFIX = '2>&1'  # Hata loglarını da yakala

# Storage ayarları
USE_LOCAL_FAKE_S3 = True
LOCAL_S3_BASE_DIR = BASE_DIR / "local_s3"
```

## Sorun Giderme

### "ModuleNotFoundError: No module named 'django_crontab'"

```bash
pip install django-crontab==0.7.1
```

### "USE_LOCAL_FAKE_S3=True ayarlayın"

Environment variable ayarlayın:

```bash
# Linux/Mac
export USE_LOCAL_FAKE_S3=true

# Windows PowerShell
$env:USE_LOCAL_FAKE_S3="true"
```

Ya da `.env` dosyasına ekleyin:

```
USE_LOCAL_FAKE_S3=true
```

### Unicode Hataları

Command'daki emoji karakterler Windows console'da sorun yaratabilir. Bu durum için tüm emoji'ler ASCII karakterlere çevrilmiştir.

## Geliştirme

### Yeni Validation Kuralı Eklemek

1. `branch_controller/csv_validator.py` dosyasını açın
2. `CSVValidator._validate_row()` metoduna yeni kural ekleyin
3. `CSVValidationError.ERROR_TYPE_CHOICES` listesine yeni hata tipi ekleyin

### Worker Sayısını Optimize Etmek

- CPU çekirdek sayınıza göre ayarlayın
- Çok fazla thread sistem performansını düşürebilir
- Önerilen: 4-8 worker

## Lisans

Bu proje dahili kullanım için geliştirilmiştir.
