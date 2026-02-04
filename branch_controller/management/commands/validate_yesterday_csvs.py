"""
Django Management Command: validate_yesterday_csvs

Her gün saat 09:00'da dün tarihli CSV dosyalarını satır satır analiz edip
format hatalarını tespit eden cronjob command'ı.

YENİ YAPIDA: Dosya bazında ÖZET kayıt, akıllı mesaj formatı, doğruluk oranı.

Kullanım:
    python manage.py validate_yesterday_csvs
    python manage.py validate_yesterday_csvs --date=2026-02-02
    python manage.py validate_yesterday_csvs --dry-run
    python manage.py validate_yesterday_csvs --workers=8
"""

import time
import boto3
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from branch_controller.models import Bayi
from branch_controller.csv_validator import CSVValidator
from branch_controller.queue_manager import ValidationQueueManager, FileTask
from branch_controller.validation_logger import ValidationLogger
from branch_controller.message_formatter import SmartMessageFormatter


class Command(BaseCommand):
    help = 'Dün tarihli CSV dosyalarını validate eder ve ÖZET raporlar'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Kontrol edilecek tarih (YYYY-MM-DD formatında). Belirtilmezse dün kullanılır.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Sadece rapor üretir, veritabanına kaydetmez'
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=4,
            help='Worker thread sayısı (default: 4)'
        )
        parser.add_argument(
            '--branch-id',
            type=str,
            help='Sadece belirli bir branch_id için işlem yap'
        )
    
    def handle(self, *args, **options):
        start_time = time.time()
        
        # Parametreleri al
        target_date_str = self._get_target_date(options['date'])
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        dry_run = options['dry_run']
        num_workers = options['workers']
        branch_id_filter = options['branch_id']
        
        self.stdout.write(self.style.SUCCESS(f'\n{"="*70}'))
        self.stdout.write(self.style.SUCCESS(f'CSV Validation Cronjob (OZET MODE)'))
        self.stdout.write(self.style.SUCCESS(f'{"="*70}'))
        self.stdout.write(f'Tarih: {target_date_str}')
        self.stdout.write(f'Worker Sayisi: {num_workers}')
        self.stdout.write(f'Dry Run: {"Evet" if dry_run else "Hayir"}')
        if branch_id_filter:
            self.stdout.write(f'Branch ID Filtresi: {branch_id_filter}')
        self.stdout.write(f'{"="*70}\n')
        
        # Logger'ı başlat
        logger = ValidationLogger()
        
        # Storage base path'i belirle
        storage_base = self._get_storage_base_path()
        
        # İşlenecek dosyaları bul
        file_tasks = self._find_csv_files(storage_base, target_date_str, branch_id_filter)
        
        if not file_tasks:
            self.stdout.write(self.style.WARNING(
                f'[!] {target_date_str} tarihinde islenecek CSV dosyasi bulunamadi.'
            ))
            return
        
        self.stdout.write(self.style.SUCCESS(
            f'[OK] {len(file_tasks)} CSV dosyasi bulundu, isleme baslaniyor...\n'
        ))
        
        # Global istatistikler
        global_total_rows = 0
        global_total_errors = 0
        category_stats = {
            'Mukemmel': 0,
            'Iyi': 0,
            'Orta': 0,
            'Kritik': 0
        }
        
        # S3 client'i hazırla (S3 mode için gerekli)
        s3_client = None
        if storage_base is None:
            s3_client = self._get_s3_client()
        
        # Validator callback fonksiyonu (YENİ: Dosya bazında özet, S3 stream desteği)
        def validate_file_callback(task: FileTask) -> Dict[str, Any]:
                nonlocal global_total_rows, global_total_errors, category_stats, s3_client
                
                # Validator oluştur
                validator = CSVValidator()
                
                # S3 veya local mode'a göre validate et
                if task.s3_key:
                    # S3 Stream mode - direk S3'ten oku
                    try:
                        response = s3_client.get_object(
                            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                            Key=task.s3_key
                        )
                        stream = response['Body']
                        is_valid, errors = validator.validate_stream(stream)
                    except Exception as e:
                        # S3 okuma hatası
                        self.stdout.write(self.style.ERROR(
                            f'[HATA] S3 stream okuma hatasi ({task.s3_key}): {str(e)}'
                        ))
                        return {
                            'processed_rows': 0,
                            'errors_found': 0
                        }
                else:
                    # Local file mode
                    is_valid, errors = validator.validate_file(str(task.file_path))
                
                # Bayi'yi al
                bayi = None
                if task.bayi_id:
                    try:
                        bayi = Bayi.objects.get(id=task.bayi_id)
                    except Bayi.DoesNotExist:
                        pass
                
                # Filename belirle
                filename = task.filename or (task.file_path.name if task.file_path else task.s3_key.split('/')[-1])
                
                # ÖZET KAYDET (tek kayıt per dosya)
                summary = logger.log_file_validation_summary(
                    filename=filename,
                    validation_date=target_date,
                    validator=validator,
                    bayi=bayi,
                    save_to_db=not dry_run
                )
                
                # Global istatistikleri güncelle
                global_total_rows += validator.validated_rows
                global_total_errors += len(errors)
                category_stats[summary['category']] += 1
                
                # Console output (akıllı format)
                console_output = SmartMessageFormatter.format_console_output(
                    filename=filename,
                    total_rows=validator.validated_rows,
                    error_count=len(errors),
                    accuracy_rate=summary['accuracy_rate']
                )
                self.stdout.write(console_output)
                
                return {
                    'processed_rows': validator.validated_rows,
                    'errors_found': len(errors)
                }
            
            # Queue Manager'ı başlat
            queue_manager = ValidationQueueManager(
                validator_callback=validate_file_callback,
                num_workers=num_workers
            )
            
            queue_manager.start()
            
            # Dosyaları kuyruğa ekle
            queue_manager.add_files(file_tasks)
            
            # İşlemlerin tamamlanmasını bekle
            self.stdout.write('\nIslemler devam ediyor...\n')
            queue_manager.wait_completion()
            
            # İstatistikleri al
            stats = queue_manager.get_stats()
            processing_time = time.time() - start_time
            
            # Session özetini logla
            logger.log_session_summary(
                total_files=stats.total_files,
                processed_files=stats.processed_files,
                total_rows=global_total_rows,
                total_errors=global_total_errors,
                processing_time=processing_time,
                category_stats=category_stats
            )
            
            # Sonuç raporunu yazdır
            self._print_summary(
                stats=stats,
                total_rows=global_total_rows,
                total_errors=global_total_errors,
                category_stats=category_stats,
                processing_time=processing_time,
                log_file=logger.get_log_file_path(),
                dry_run=dry_run
            )
    
    def _get_target_date(self, date_str: Optional[str]) -> str:
        """Hedef tarihi belirler (YYYY-MM-DD formatında)"""
        if date_str:
            try:
                # Tarih formatını doğrula
                datetime.strptime(date_str, '%Y-%m-%d')
                return date_str
            except ValueError:
                raise CommandError('Gecersiz tarih formati. YYYY-MM-DD formatinda olmali.')
        else:
            # Dün
            yesterday = datetime.now() - timedelta(days=1)
            return yesterday.strftime('%Y-%m-%d')
    
    def _get_storage_base_path(self) -> Optional[Path]:
        """Storage base path'ini döndürür. S3 mode için None döner."""
        if getattr(settings, 'USE_LOCAL_FAKE_S3', False):
            base_path = getattr(settings, 'LOCAL_S3_BASE_DIR', settings.BASE_DIR / 'local_s3')
            return Path(base_path) / 'uploads'
        else:
            # S3 mode - return None to indicate S3 usage
            return None
    
    def _list_s3_csv_files(
        self,
        target_date_ddmmyyyy: str,
        branch_id_filter: Optional[str] = None
    ) -> list[tuple[str, str, Optional[int], str]]:
        """
        S3'ten CSV dosyalarını listeler ve metadata döner.
        
        Returns:
            List of tuples: (s3_key, branch_id, bayi_id, filename)
        """
        import re
        
        s3_client = self._get_s3_client()
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        prefix = "uploads/"
        
        file_metadata = []
        
        try:
            # S3'teki tüm objeleri listele
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
            
            for page in pages:
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    key = obj['Key']
                    
                    # Key formatı: uploads/{branch_id}/branch_{branch_id}_{DDMMYYYY}/file.csv
                    # Örnek: uploads/10000/branch_10000_03022026/branch_10000_01_03022026.csv
                    
                    if not key.endswith('.csv'):
                        continue
                    
                    # Key'i parçalara ayır
                    parts = key.split('/')
                    if len(parts) < 4:
                        continue
                    
                    # uploads/{branch_id}/{folder_name}/{file.csv}
                    branch_id = parts[1]
                    folder_name = parts[2]
                    filename = parts[3]
                    
                    # Branch ID filtresi
                    if branch_id_filter and branch_id != branch_id_filter:
                        continue
                    
                    # Folder name pattern kontrolü
                    pattern = rf'^branch_{re.escape(branch_id)}_(\d{{8}})$'
                    match = re.match(pattern, folder_name)
                    
                    if not match:
                        continue
                    
                    folder_date = match.group(1)
                    
                    # Tarih kontrolü
                    if folder_date != target_date_ddmmyyyy:
                        continue
                    
                    # Bayi'yi bul
                    bayi = None
                    try:
                        bayi = Bayi.objects.filter(branch_id=branch_id).first()
                    except Exception:
                        pass
                    
                    file_metadata.append((key, branch_id, bayi.id if bayi else None, filename))
            
        except Exception as e:
            raise CommandError(f'S3 listeleme hatasi: {str(e)}')
        
        return file_metadata
    
    def _get_s3_client(self):
        """Returns configured S3 client"""
        return boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
    
    def _find_csv_files(
        self,
        storage_base: Optional[Path],
        target_date: str,
        branch_id_filter: Optional[str] = None
    ) -> list[FileTask]:
        """
        Belirtilen tarih için CSV dosyalarını bulur.
        
        YENİ Klasör yapısı: storage_base/{branch_id}/branch_{branch_id}_{DDMMYYYY}/dosya.csv
        Örnek: uploads/10000/branch_10000_03022026/branch_10000_01_03022026.csv
        
        Returns:
            list[FileTask] - FileTask objects with either file_path (local) or s3_key (S3)
        """
        file_tasks = []
        
        # Target date'i DDMMYYYY formatına çevir (YYYY-MM-DD -> DDMMYYYY)
        # Örnek: 2026-02-03 -> 03022026
        try:
            date_obj = datetime.strptime(target_date, '%Y-%m-%d')
            target_date_ddmmyyyy = date_obj.strftime('%d%m%Y')
        except ValueError:
            raise CommandError(f'Gecersiz target_date formati: {target_date}')
        
        # S3 mode
        if storage_base is None:
            self.stdout.write('S3 modunda calisiliyor (stream mode - indirme yok)...')
            
            # S3'ten dosyaları listele
            s3_files = self._list_s3_csv_files(target_date_ddmmyyyy, branch_id_filter)
            
            if not s3_files:
                return file_tasks
            
            # FileTask'ları oluştur (indirme yok, sadece metadata)
            for s3_key, branch_id, bayi_id, filename in s3_files:
                file_tasks.append(FileTask(
                    file_path=None,  # S3 mode için None
                    branch_id=branch_id,
                    bayi_id=bayi_id,
                    s3_key=s3_key,
                    filename=filename
                ))
                self.stdout.write(f'Listelendi: {s3_key}')
            
            return file_tasks
        
        # Local storage mode
        if not storage_base.exists():
            raise CommandError(f'Storage klasoru bulunamadi: {storage_base}')
        
        # Branch ID klasörlerini tara
        for branch_dir in storage_base.iterdir():
            if not branch_dir.is_dir():
                continue
            
            branch_id = branch_dir.name
            
            # Branch ID filtresi varsa kontrol et
            if branch_id_filter and branch_id != branch_id_filter:
                continue
            
            # Bayi'yi bul
            bayi = None
            try:
                bayi = Bayi.objects.filter(branch_id=branch_id).first()
            except Exception:
                pass
            
            # Branch klasörü içindeki tüm klasörleri tara
            # Klasör adı formatı: branch_{branch_id}_{DDMMYYYY}
            import re
            pattern = rf'^branch_{re.escape(branch_id)}_(\d{{8}})$'
            
            for folder in branch_dir.iterdir():
                if not folder.is_dir():
                    continue
                
                # Klasör adını kontrol et
                match = re.match(pattern, folder.name)
                if not match:
                    continue
                
                # Tarih kısmını çıkar
                folder_date = match.group(1)
                
                # Target date ile karşılaştır
                if folder_date != target_date_ddmmyyyy:
                    continue
                
                # Bu klasör içindeki CSV dosyalarını bul
                csv_files = list(folder.glob('*.csv'))
                
                for csv_file in csv_files:
                    file_tasks.append(FileTask(
                        file_path=csv_file,
                        branch_id=branch_id,
                        bayi_id=bayi.id if bayi else None,
                        filename=csv_file.name
                    ))
        
        return file_tasks
    
    def _print_summary(
        self,
        stats,
        total_rows: int,
        total_errors: int,
        category_stats: Dict[str, int],
        processing_time: float,
        log_file: Path,
        dry_run: bool
    ):
        """Özet raporu yazdırır"""
        self.stdout.write(f'\n{"="*70}')
        self.stdout.write(self.style.SUCCESS('ISLEM TAMAMLANDI'))
        self.stdout.write(f'{"="*70}')
        
        self.stdout.write(f'\nOZET ISTATISTIKLER:')
        self.stdout.write(f'  - Taranan Dosya: {stats.total_files}')
        self.stdout.write(f'  - Islenen Dosya: {stats.processed_files}')
        self.stdout.write(f'  - Toplam Satir: {total_rows:,}')
        self.stdout.write(f'  - Bulunan Hata: {total_errors:,}')
        self.stdout.write(f'  - Islem Suresi: {processing_time:.2f} saniye')
        
        if processing_time > 0:
            rows_per_sec = total_rows / processing_time
            self.stdout.write(f'  - Islem Hizi: {rows_per_sec:.1f} satir/saniye')
        
        # Doğruluk kategorileri
        self.stdout.write(f'\nDOGRULUK KATEGORILERI:')
        for category, count in category_stats.items():
            if count > 0:
                self.stdout.write(f'  - {category}: {count} dosya')
        
        self.stdout.write(f'\nLog Dosyasi: {log_file}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\n[!] DRY RUN - Hatalar veritabanina kaydedilmedi.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                '\n[OK] Ozetler veritabanina kaydedildi.'
            ))
        
        self.stdout.write(f'{"="*70}\n')
