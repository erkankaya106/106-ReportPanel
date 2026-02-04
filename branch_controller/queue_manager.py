"""
Queue Manager - Performans koruyucu kuyruk sistemi ile CSV satırlarını işler.

Custom Python Thread + Queue yapısı kullanarak:
- Sunucuyu yormadan işlem yapar
- Configurable worker thread sayısı
- Memory-safe chunk processing
- Graceful shutdown
- Progress tracking
"""

import threading
import queue
import time
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ProcessingStats:
    """İşlem istatistiklerini tutar"""
    total_files: int = 0
    processed_files: int = 0
    total_rows: int = 0
    processed_rows: int = 0
    errors_found: int = 0
    start_time: float = 0
    end_time: float = 0
    
    def get_duration(self) -> float:
        """İşlem süresini saniye cinsinden döndürür"""
        if self.end_time > 0:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    def get_rows_per_second(self) -> float:
        """Saniyede işlenen satır sayısını döndürür"""
        duration = self.get_duration()
        if duration > 0:
            return self.processed_rows / duration
        return 0


@dataclass
class FileTask:
    """İşlenecek dosya görevi"""
    file_path: Optional[Path] = None  # None for S3 mode
    branch_id: Optional[str] = None
    bayi_id: Optional[int] = None
    s3_key: Optional[str] = None  # S3 key if streaming from S3
    filename: Optional[str] = None  # Explicit filename for display


class ValidationQueueManager:
    """
    CSV dosyalarını kuyruk sistemiyle validate eden yönetici.
    
    Özellikler:
    - Multi-threaded processing
    - Configurable worker sayısı
    - Memory-safe chunk processing
    - Graceful shutdown
    - Progress tracking
    """
    
    def __init__(
        self,
        validator_callback: Callable[[FileTask], Dict[str, Any]],
        num_workers: int = 4,
        max_queue_size: int = 1000,
        chunk_size: int = 100
    ):
        """
        Args:
            validator_callback: Dosya validate eden fonksiyon (FileTask) -> result
            num_workers: Worker thread sayısı (default: 4)
            max_queue_size: Maksimum kuyruk boyutu (default: 1000)
            chunk_size: Aynı anda işlenecek satır sayısı (default: 100)
        """
        self.validator_callback = validator_callback
        self.num_workers = num_workers
        self.max_queue_size = max_queue_size
        self.chunk_size = chunk_size
        
        self.task_queue: queue.Queue[Optional[FileTask]] = queue.Queue(maxsize=max_queue_size)
        self.workers: List[threading.Thread] = []
        self.stop_event = threading.Event()
        self.stats = ProcessingStats()
        self.stats_lock = threading.Lock()
        
        # Progress callback (opsiyonel)
        self.progress_callback: Optional[Callable[[ProcessingStats], None]] = None
    
    def set_progress_callback(self, callback: Callable[[ProcessingStats], None]):
        """Progress callback fonksiyonu ayarlar"""
        self.progress_callback = callback
    
    def _worker(self, worker_id: int):
        """Worker thread fonksiyonu"""
        while not self.stop_event.is_set():
            try:
                # Timeout ile task al (graceful shutdown için)
                task = self.task_queue.get(timeout=0.5)
                
                # Poison pill kontrolü (shutdown sinyali)
                if task is None:
                    break
                
                # Dosyayı işle
                try:
                    result = self.validator_callback(task)
                    
                    # İstatistikleri güncelle
                    with self.stats_lock:
                        self.stats.processed_files += 1
                        self.stats.processed_rows += result.get('processed_rows', 0)
                        self.stats.errors_found += result.get('errors_found', 0)
                        
                        # Progress callback varsa çağır
                        if self.progress_callback:
                            self.progress_callback(self.stats)
                
                except Exception as e:
                    print(f"[Worker-{worker_id}] Dosya işleme hatası: {task.file_path} - {e}")
                
                finally:
                    self.task_queue.task_done()
            
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Worker-{worker_id}] Beklenmeyen hata: {e}")
    
    def start(self):
        """Worker thread'leri başlatır"""
        self.stop_event.clear()
        self.stats.start_time = time.time()
        
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker,
                args=(i,),
                name=f"ValidationWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        
        print(f"[QueueManager] {self.num_workers} worker thread başlatıldı")
    
    def add_file(self, file_path: Path, branch_id: Optional[str] = None, bayi_id: Optional[int] = None):
        """Kuyruğa dosya ekler"""
        task = FileTask(file_path=file_path, branch_id=branch_id, bayi_id=bayi_id)
        self.task_queue.put(task)
        
        with self.stats_lock:
            self.stats.total_files += 1
    
    def add_files(self, file_tasks: List[FileTask]):
        """Kuyruğa birden fazla dosya ekler"""
        for task in file_tasks:
            self.task_queue.put(task)
        
        with self.stats_lock:
            self.stats.total_files += len(file_tasks)
    
    def wait_completion(self, timeout: Optional[float] = None):
        """Tüm task'lerin tamamlanmasını bekler"""
        try:
            # Kuyruk boşalana kadar bekle
            self.task_queue.join()
            
            # Worker'lara poison pill gönder (shutdown sinyali)
            for _ in range(self.num_workers):
                self.task_queue.put(None)
            
            # Worker'ların bitmesini bekle
            for worker in self.workers:
                worker.join(timeout=timeout)
            
            self.stats.end_time = time.time()
            print(f"[QueueManager] Tüm işlemler tamamlandı")
            
        except KeyboardInterrupt:
            print(f"[QueueManager] İşlem kullanıcı tarafından durduruldu")
            self.shutdown()
    
    def shutdown(self):
        """Acil durumda worker'ları güvenli şekilde kapatır"""
        print(f"[QueueManager] Shutdown başlatılıyor...")
        self.stop_event.set()
        
        # Worker'ları bekle
        for worker in self.workers:
            worker.join(timeout=2.0)
        
        self.stats.end_time = time.time()
        print(f"[QueueManager] Shutdown tamamlandı")
    
    def get_stats(self) -> ProcessingStats:
        """İşlem istatistiklerini döndürür"""
        with self.stats_lock:
            return ProcessingStats(
                total_files=self.stats.total_files,
                processed_files=self.stats.processed_files,
                total_rows=self.stats.total_rows,
                processed_rows=self.stats.processed_rows,
                errors_found=self.stats.errors_found,
                start_time=self.stats.start_time,
                end_time=self.stats.end_time
            )
    
    def print_progress(self):
        """Şu anki ilerlemeyi yazdırır"""
        stats = self.get_stats()
        duration = stats.get_duration()
        rows_per_sec = stats.get_rows_per_second()
        
        print(f"[Progress] Dosya: {stats.processed_files}/{stats.total_files}, "
              f"Satır: {stats.processed_rows}, "
              f"Hata: {stats.errors_found}, "
              f"Süre: {duration:.1f}s, "
              f"Hız: {rows_per_sec:.1f} satır/s")


class ChunkedFileReader:
    """
    Büyük dosyaları memory-safe şekilde chunk'lara bölerek okur.
    """
    
    def __init__(self, file_path: Path, chunk_size: int = 1000):
        """
        Args:
            file_path: Okunacak dosya
            chunk_size: Her chunk'ta kaç satır olacak
        """
        self.file_path = file_path
        self.chunk_size = chunk_size
    
    def read_chunks(self):
        """
        Dosyayı chunk'lara bölerek okur.
        
        Yields:
            (chunk_lines, start_line_number) tuple'ları
        """
        with open(self.file_path, 'r', encoding='utf-8') as f:
            line_number = 0
            chunk = []
            
            for line in f:
                line_number += 1
                chunk.append((line_number, line.strip()))
                
                if len(chunk) >= self.chunk_size:
                    yield chunk, line_number - len(chunk) + 1
                    chunk = []
            
            # Son chunk'ı da yield et
            if chunk:
                yield chunk, line_number - len(chunk) + 1
