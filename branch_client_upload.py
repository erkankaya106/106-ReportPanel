#!/usr/bin/env python
"""
Branch Client - CSV Upload via ZIP

Bu script bayilerin CSV dosyalarını ZIP formatında yüklemesini sağlar.
Klasördeki tüm CSV dosyalarını toplar, ZIP oluşturur ve tek seferde yükler.

Kullanım:
1. Script başındaki ayarları düzenleyin (API_URL, BRANCH_ID, SECRET_KEY, FOLDER_PATH)
2. CSV dosyalarınızı belirtilen klasöre koyun
3. Script'i çalıştırın: python branch_client_upload.py

CSV Dosya Adı Formatı:
    branch_{branch_id}_{NN}_{DDMMYYYY}.csv
    Örnek: branch_11000_01_03022026.csv

Klasör Adı Formatı (opsiyonel):
    branch_{branch_id}_{YYYYMMDD} veya branch_{branch_id}_{DDMMYYYY}
    Örnek: branch_11000_20260203 veya branch_11000_03022026
"""

import hashlib
import hmac
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import List, Tuple
from datetime import datetime

import requests


# ============================================================================
# AYARLAR - BURASI DÜZENLENMELİ
# ============================================================================

API_URL = "http://127.0.0.1:8000/enterprise-upload/"
BRANCH_ID = "11000"
SECRET_KEY = "keybilyoner"

# CSV dosyalarının bulunduğu klasör
# Örnek: r"C:\Users\erkan.kaya\Desktop\branch_11000_20260203"
FOLDER_PATH = r"C:\Users\erkan.kaya\Desktop\branch_11000_03022026"

# ============================================================================


def convert_yyyymmdd_to_ddmmyyyy(date_str: str) -> str:
    """
    YYYYMMDD formatını DDMMYYYY formatına çevirir.
    Örnek: 20260203 -> 03022026
    """
    if len(date_str) == 8 and date_str.isdigit():
        year = date_str[0:4]
        month = date_str[4:6]
        day = date_str[6:8]
        return f"{day}{month}{year}"
    return date_str


def extract_date_from_folder_or_files(folder: Path, files: List[Path], branch_id: str) -> str:
    """
    Klasör adından veya CSV dosyalarından tarihi DDMMYYYY formatında çıkarır.
    
    Önce klasör adından denenir (branch_11000_20260203 veya branch_11000_03022026)
    Sonra ilk CSV dosyasından parse edilir.
    
    Returns:
        str: DDMMYYYY formatında tarih (örn: "03022026")
    """
    # Önce klasör adından dene
    folder_name = folder.name
    
    # Pattern 1: branch_{branch_id}_{date}
    if folder_name.startswith(f"branch_{branch_id}_"):
        date_part = folder_name.split('_')[-1]
        
        # YYYYMMDD formatı mı? (20260203)
        if len(date_part) == 8 and date_part.isdigit():
            # İlk 4 karakter yıl gibi görünüyorsa (20xx)
            if date_part.startswith('20'):
                return convert_yyyymmdd_to_ddmmyyyy(date_part)
            else:
                # Zaten DDMMYYYY formatında olabilir
                return date_part
    
    # CSV dosyasından tarihi çıkar
    if not files:
        raise ValueError("Tarih belirlenemedi: Klasör adı uygun değil ve CSV dosyası yok")
    
    # İlk CSV dosyasından: branch_11000_01_03022026.csv
    first_file = files[0].name
    parts = first_file.replace('.csv', '').split('_')
    
    if len(parts) < 4:
        raise ValueError(f"CSV dosya adı formatı hatalı: {first_file}")
    
    date_part = parts[-1]  # Son kısım tarih olmalı
    
    # Tarih kontrolü
    if len(date_part) != 8 or not date_part.isdigit():
        raise ValueError(f"Tarih formatı hatalı: {date_part} (DDMMYYYY veya YYYYMMDD olmalı)")
    
    # YYYYMMDD ise çevir
    if date_part.startswith('20'):
        return convert_yyyymmdd_to_ddmmyyyy(date_part)
    
    return date_part


def convert_csv_filename_to_ddmmyyyy(filename: str, branch_id: str, target_date_ddmmyyyy: str) -> str:
    """
    CSV dosya adını DDMMYYYY formatına çevirir.
    
    Eğer dosya adı YYYYMMDD formatındaysa (branch_11000_01_20260102.csv),
    DDMMYYYY formatına çevirir (branch_11000_01_02012026.csv).
    
    Eğer zaten DDMMYYYY formatındaysa, olduğu gibi döner.
    
    Args:
        filename: CSV dosya adı (örn: branch_11000_01_20260102.csv)
        branch_id: Branch ID
        target_date_ddmmyyyy: Hedef tarih (DDMMYYYY formatında)
    
    Returns:
        str: DDMMYYYY formatında yeni dosya adı
    """
    # Dosya adını parse et: branch_11000_01_20260102.csv
    name_without_ext = filename.replace('.csv', '')
    parts = name_without_ext.split('_')
    
    if len(parts) < 4:
        # Format uygun değilse olduğu gibi dön
        return filename
    
    # Parts: ['branch', '11000', '01', '20260102']
    date_part = parts[-1]
    
    # Eğer tarih YYYYMMDD formatındaysa (20xx ile başlıyorsa)
    if len(date_part) == 8 and date_part.isdigit() and date_part.startswith('20'):
        # DDMMYYYY'ye çevir
        date_ddmmyyyy = convert_yyyymmdd_to_ddmmyyyy(date_part)
        
        # Yeni dosya adı oluştur
        parts[-1] = date_ddmmyyyy
        new_name = '_'.join(parts) + '.csv'
        return new_name
    
    # Zaten DDMMYYYY formatındaysa veya bilinmeyen formatsa, olduğu gibi dön
    return filename


def create_zip_from_csvs(csv_files: List[Path], branch_id: str, date_ddmmyyyy: str) -> Path:
    """
    CSV dosyalarından doğru yapıda ZIP oluşturur.
    
    NOT: CSV dosya adları ZIP içinde DDMMYYYY formatına otomatik çevrilir.
    
    Oluşturulan yapı:
        branch_{branch_id}_{DDMMYYYY}.zip
        └── branch_{branch_id}_{DDMMYYYY}/
            ├── branch_{branch_id}_01_{DDMMYYYY}.csv
            ├── branch_{branch_id}_02_{DDMMYYYY}.csv
            └── ...
    
    Args:
        csv_files: CSV dosyalarının listesi
        branch_id: Branch ID
        date_ddmmyyyy: Tarih (DDMMYYYY formatında)
    
    Returns:
        Path: Oluşturulan ZIP dosyasının yolu
    """
    folder_name = f"branch_{branch_id}_{date_ddmmyyyy}"
    zip_filename = f"{folder_name}.zip"
    
    # Geçici dizinde ZIP oluştur
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    zip_path = temp_dir / zip_filename
    
    print(f"\nZIP olusturuluyor: {zip_filename}")
    print(f"Hedef klasor: {folder_name}/")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for csv_file in sorted(csv_files):
            # Dosya adını DDMMYYYY formatına çevir
            new_filename = convert_csv_filename_to_ddmmyyyy(csv_file.name, branch_id, date_ddmmyyyy)
            
            # ZIP içinde klasör yapısı: folder_name/new_filename
            arcname = f"{folder_name}/{new_filename}"
            zipf.write(csv_file, arcname=arcname)
            
            # Dosya adı değiştiyse göster
            if new_filename != csv_file.name:
                print(f"  + {csv_file.name} -> {new_filename}")
            else:
                print(f"  + {csv_file.name}")
    
    file_size_kb = zip_path.stat().st_size / 1024
    print(f"\nZIP olusturuldu: {zip_path}")
    print(f"Boyut: {file_size_kb:.2f} KB")
    
    return zip_path


def make_signature(branch_id: str, secret_key: str, filename: str, timestamp: str) -> str:
    """HMAC imzası oluşturur."""
    message = f"{branch_id}{filename}{timestamp}"
    return hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def iter_csv_files(folder: Path) -> List[Path]:
    """Klasördeki tüm CSV dosyalarını listeler."""
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Klasor bulunamadi veya klasor degil: {folder}")
    
    csv_files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    return sorted(csv_files)


def is_filename_valid_for_branch(filename: str, branch_id: str) -> bool:
    """Dosya adının branch ID ile uyumlu olup olmadığını kontrol eder."""
    return filename.startswith(f"branch_{branch_id}_")


def upload_zip(zip_path: Path, branch_id: str, secret_key: str, api_url: str) -> Tuple[bool, int, str]:
    """
    ZIP dosyasını API'ye yükler.
    
    Returns:
        Tuple[bool, int, str]: (başarılı mı, HTTP status code, mesaj)
    """
    filename = zip_path.name
    timestamp = str(int(time.time()))
    signature = make_signature(branch_id, secret_key, filename, timestamp)
    
    headers = {
        "X-Branch-ID": branch_id,
        "X-Signature": signature,
        "X-Timestamp": timestamp,
    }
    
    print(f"\nYukleniyor: {api_url}")
    print(f"Headers:")
    print(f"  X-Branch-ID: {branch_id}")
    print(f"  X-Signature: {signature[:20]}...")
    print(f"  X-Timestamp: {timestamp}")
    
    try:
        with zip_path.open("rb") as f:
            files = {"file": (filename, f, "application/zip")}
            resp = requests.post(api_url, headers=headers, files=files, timeout=120)
    except requests.RequestException as e:
        return False, 0, f"Request hatasi: {e}"
    
    # Response parse et
    try:
        data = resp.json()
        msg = data.get("message", str(data))
        
        # Eğer csv_count varsa ekle
        if "csv_count" in data:
            msg += f" ({data['csv_count']} CSV dosyasi)"
    except ValueError:
        msg = resp.text
    
    success = resp.status_code == 200
    return success, resp.status_code, msg


def main() -> None:
    """Ana fonksiyon."""
    print("=" * 70)
    print("Branch Client - ZIP Upload")
    print("=" * 70)
    print(f"Branch ID: {BRANCH_ID}")
    print(f"Klasor: {FOLDER_PATH}")
    print(f"API URL: {API_URL}")
    print("=" * 70)
    
    folder = Path(FOLDER_PATH)
    
    # 1. CSV dosyalarını topla
    try:
        csv_files = iter_csv_files(folder)
    except FileNotFoundError as e:
        print(f"\n[HATA] {e}")
        sys.exit(1)
    
    if not csv_files:
        print(f"\n[HATA] Klasorde CSV dosyasi bulunamadi: {folder}")
        sys.exit(1)
    
    print(f"\n{len(csv_files)} CSV dosyasi bulundu:")
    for csv_file in csv_files:
        print(f"  - {csv_file.name}")
    
    # Dosya adı kontrolü
    invalid_files = [f for f in csv_files if not is_filename_valid_for_branch(f.name, BRANCH_ID)]
    if invalid_files:
        print(f"\n[UYARI] Asagidaki dosyalar branch_{BRANCH_ID}_ ile baslamiyor:")
        for f in invalid_files:
            print(f"  - {f.name}")
        
        # Devam et mi?
        response = input("\nYine de devam edilsin mi? (E/h): ")
        if response.lower() not in ['e', 'evet', 'yes', 'y', '']:
            print("Islem iptal edildi.")
            sys.exit(0)
    
    # 2. Tarih çıkar
    try:
        date_ddmmyyyy = extract_date_from_folder_or_files(folder, csv_files, BRANCH_ID)
        print(f"\nTarih tespit edildi: {date_ddmmyyyy} (DDMMYYYY)")
    except ValueError as e:
        print(f"\n[HATA] {e}")
        sys.exit(1)
    
    # 3. ZIP oluştur
    try:
        zip_path = create_zip_from_csvs(csv_files, BRANCH_ID, date_ddmmyyyy)
    except Exception as e:
        print(f"\n[HATA] ZIP olusturma hatasi: {e}")
        sys.exit(1)
    
    # 4. ZIP yükle
    try:
        success, status_code, message = upload_zip(zip_path, BRANCH_ID, SECRET_KEY, API_URL)
        
        print("\n" + "=" * 70)
        if success:
            print("[BASARILI] Yukleme tamamlandi!")
            print(f"HTTP Status: {status_code}")
            print(f"Mesaj: {message}")
            print("=" * 70)
        else:
            print("[HATA] Yukleme basarisiz!")
            print(f"HTTP Status: {status_code}")
            print(f"Mesaj: {message}")
            print("=" * 70)
            
            # Hata durumunda ZIP'i sakla
            print(f"\n[BILGI] Hata analizi icin ZIP dosyasi saklandi: {zip_path}")
            sys.exit(1)
    
    except Exception as e:
        print(f"\n[HATA] Yukleme hatasi: {e}")
        print(f"[BILGI] ZIP dosyasi saklandi: {zip_path}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # 5. Başarılıysa ZIP'i temizle
    try:
        zip_path.unlink()
        print(f"\n[BILGI] Gecici ZIP dosyasi temizlendi.")
    except Exception as e:
        print(f"\n[UYARI] ZIP temizleme hatasi: {e}")
    
    print("\nIslem tamamlandi!")


if __name__ == "__main__":
    main()
