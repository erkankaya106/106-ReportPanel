#!/usr/bin/env python
"""
Branch Client — ZIP Upload (Referans Entegrasyon Scripti)

Bu script, herhangi bir yazılım dilinde entegrasyon yapacak geliştiriciler için
referans olarak hazırlanmıştır. Adımlar dil bağımsız pseudocode ile açıklanmıştır.

Bağımlılıklar: requests
    pip install requests
"""

import hashlib
import hmac
import tempfile
import time
import zipfile
from pathlib import Path

import requests


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PROTOKOL ÖZETI — tüm diller için geçerlidir                               ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  ENDPOINT   :  POST /enterprise-upload/                                     ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  HEADERS    :  X-Branch-ID   →  bayi kimliği (string)                       ║
# ║                X-Signature   →  HMAC-SHA256 imzası (hex string, 64 char)    ║
# ║                X-Timestamp   →  Unix timestamp, saniye cinsinden (string)   ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  BODY       :  multipart/form-data                                          ║
# ║                key = "file",  value = ZIP dosyası (binary)                  ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  İMZA FORMÜLÜ                                                               ║
# ║    message   = branch_id + zip_filename + timestamp   ← string birleştirme  ║
# ║    signature = HMAC-SHA256(key=secret_key, msg=message).hexdigest()         ║
# ║                                                                              ║
# ║  Örnek:  branch_id="41000", filename="41000.zip", ts="1740000000"           ║
# ║    msg = "41000" + "41000.zip" + "1740000000"                               ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  ZIP DOSYASI YAPISI (backend bu yapıyı zorunlu kılar)                       ║
# ║                                                                              ║
# ║    41000.zip                          ← {branch_id}.zip                     ║
# ║    └── branch_id=41000/              ← ZIP içinde Hive-partition klasörü    ║
# ║        ├── provider_id=01/                                                  ║
# ║        │   └── date=2026-02-26/      ← YYYY-MM-DD formatında tarih          ║
# ║        │       ├── bet.csv                                                  ║
# ║        │       ├── win.csv                                                  ║
# ║        │       └── canceled.csv                                             ║
# ║        └── provider_id=02/                                                  ║
# ║            └── date=2026-02-26/                                             ║
# ║                ├── bet.csv                                                  ║
# ║                ├── win.csv                                                  ║
# ║                └── canceled.csv                                             ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  CSV İÇERİK KURALLARI                                                       ║
# ║                                                                              ║
# ║  bet.csv                                                                    ║
# ║    Header : roundId;gameId;createDate;updateDate;betAmount;status           ║
# ║    status : win | lost | pending | canceled                                 ║
# ║    Örnek  : 386754af-2164-439d-a078-8872009a8235;97;2026-02-03 01:08:05;   ║
# ║             2026-02-03 01:08:06;5,00;lost                                  ║
# ║                                                                              ║
# ║  win.csv                                                                    ║
# ║    Header : roundId;gameId;createDate;updateDate;winAmount                  ║
# ║    Örnek  : 386754af-2164-439d-a078-8872009a8235;97;2026-02-03 01:08:05;   ║
# ║             2026-02-03 01:08:06;10,00                                       ║
# ║                                                                              ║
# ║  canceled.csv                                                               ║
# ║    Header : roundId;gameId;createDate;updateDate;betAmount                  ║
# ║    Örnek  : 386754af-2164-439d-a078-8872009a8235;97;2026-02-03 01:08:05;   ║
# ║             2026-02-03 01:08:06;5,00                                        ║
# ║                                                                              ║
# ║  Ortak kurallar:                                                             ║
# ║    Ayraç  : noktalı virgül (;)                                               ║
# ║    Decimal: virgül (,)  →  "12,50"  doğru,  "12.50"  hatalı                ║
# ║    Tarih  : YYYY-MM-DD HH:MM:SS                                              ║
# ║    Negatif betAmount / winAmount → reddedilir                                ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  BAŞARI YANITI (HTTP 200)                                                   ║
# ║    { "status": "success", "folder": "branch_id=41000", "csv_count": N }    ║
# ║  HATA YANITI (HTTP 4xx / 5xx)                                               ║
# ║    { "status": "error", "message": "hata açıklaması" }                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


# ─── ADIM 1: AYARLAR ─────────────────────────────────────────────────────────
# Her bayi için bu üç değer backend tarafından verilir.
# FOLDER_PATH: "branch_id={id}" formatında isimlendirilmiş kök klasörün tam yolu.
#
# Klasör yapısı:
#   branch_id=41000/
#     provider_id=01/
#       date=2026-02-26/
#         bet.csv
#         win.csv
#         canceled.csv

API_URL     = "http://18.153.12.59/enterprise-upload/"
BRANCH_ID   = "106"
SECRET_KEY  = "106dijital"
FOLDER_PATH = r"C:\Users\erkan.kaya\Desktop\branch_id=106"


# ─── ADIM 2: KAYNAK KLASÖRÜ DOĞRULA ──────────────────────────────────────────
# Klasör adının "branch_id={id}" formatında olduğunu ve içinde en az bir
# provider_id= alt klasörü bulunduğunu kontrol et.
#
# Pseudocode:
#   folder_name = basename(FOLDER_PATH)     # "branch_id=41000"
#   assert folder_name == f"branch_id={BRANCH_ID}"
#   provider_dirs = list subdirs matching "provider_id=*"

folder = Path(FOLDER_PATH)
folder_name = folder.name  # branch_id=41000

if folder_name != f"branch_id={BRANCH_ID}":
    raise ValueError(
        f"Klasör adı hatalı. Beklenen: branch_id={BRANCH_ID}, Bulunan: {folder_name}"
    )

provider_dirs = [p for p in folder.iterdir() if p.is_dir() and p.name.startswith("provider_id=")]

if not provider_dirs:
    raise ValueError("Klasörde hiç provider_id= alt dizini bulunamadı")

print(f"Kaynak klasör  : {folder}")
print(f"Provider sayısı: {len(provider_dirs)}")
for pd in sorted(provider_dirs):
    date_dirs = [d for d in pd.iterdir() if d.is_dir() and d.name.startswith("date=")]
    print(f"  {pd.name}/")
    for dd in sorted(date_dirs):
        csvs = sorted(dd.glob("*.csv"))
        print(f"    {dd.name}/  ({len(csvs)} csv)")
        for c in csvs:
            print(f"      {c.name}")


# ─── ADIM 3: ZIP OLUŞTUR ─────────────────────────────────────────────────────
# ZIP adı: {branch_id}.zip  (örn: 41000.zip)
# ZIP içinde tüm klasör hiyerarşisi korunur.
#
# Pseudocode:
#   zip_name = BRANCH_ID + ".zip"           # "41000.zip"
#   zip = create_zip(zip_name)
#   for each file in folder recursively:
#       zip.add(file, arcname = folder_name + "/" + relative_path_of_file)

zip_name = f"{BRANCH_ID}.zip"
zip_path = Path(tempfile.gettempdir()) / zip_name

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for file_path in folder.rglob("*"):
        if file_path.is_file():
            # ZIP içinde arc path: branch_id=41000/provider_id=01/date=2026-02-26/bet.csv
            arcname = folder_name + "/" + file_path.relative_to(folder).as_posix()
            zf.write(file_path, arcname=arcname)

print(f"\nZIP oluşturuldu: {zip_path}  ({zip_path.stat().st_size / 1024:.1f} KB)")


# ─── ADIM 4: İMZA HESAPLA ────────────────────────────────────────────────────
# İmza replay saldırılarına karşı timestamp içerir.
# Backend ±5 dakika dışındaki istekleri reddeder.
#
# Pseudocode:
#   timestamp = current_unix_time_as_string()      # örn: "1740000000"
#   message   = BRANCH_ID + zip_name + timestamp   # string concat, araya ayraç YOK
#   signature = hmac_sha256(key=SECRET_KEY, msg=message).to_hex()

timestamp = str(int(time.time()))
message   = BRANCH_ID + zip_name + timestamp
signature = hmac.new(
    SECRET_KEY.encode("utf-8"),
    message.encode("utf-8"),
    hashlib.sha256
).hexdigest()

print(f"\nTimestamp : {timestamp}")
print(f"Imza      : {signature[:20]}...")


# ─── ADIM 5: POST İSTEĞİ GÖNDER ──────────────────────────────────────────────
# ZIP dosyası multipart/form-data ile "file" anahtarıyla gönderilir.
# Tüm kimlik bilgileri header'larda taşınır.
#
# Pseudocode:
#   headers = {
#       "X-Branch-ID"  : BRANCH_ID,
#       "X-Signature"  : signature,
#       "X-Timestamp"  : timestamp,
#   }
#   response = http_post(
#       url     = API_URL,
#       headers = headers,
#       body    = multipart_form(file = open(zip_path, "rb")),
#   )

headers = {
    "X-Branch-ID" : BRANCH_ID,
    "X-Signature" : signature,
    "X-Timestamp" : timestamp,
}

print(f"\nGonderiliyor → {API_URL}")

with zip_path.open("rb") as f:
    response = requests.post(
        API_URL,
        headers=headers,
        files={"file": (zip_name, f, "application/zip")},
        timeout=120,
    )


# ─── ADIM 6: SONUCU GÖSTER ───────────────────────────────────────────────────
# HTTP 200 → başarı,  4xx/5xx → hata mesajı "message" alanında döner.

print(f"\nHTTP {response.status_code}")
print(response.json())


# ─── TEMİZLİK ────────────────────────────────────────────────────────────────
zip_path.unlink(missing_ok=True)
