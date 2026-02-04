# Branch CSV Upload - Quick Start Guide

## Overview

Upload multiple CSV files in a single compressed ZIP file for faster, more efficient transfers.

## Step-by-Step Guide

### 1. Prepare Your CSV Files

Create CSV files with this naming format:
```
branch_{your_branch_id}_{sequence}_{DDMMYYYY}.csv
```

**Example** (for branch 10000 on 3rd Feb 2026):
```
branch_10000_01_03022026.csv
branch_10000_02_03022026.csv
branch_10000_03_03022026.csv
```

**Important**: 
- All files must have the **same date**
- Sequence numbers: 01, 02, 03, ... up to 99
- Date format: DDMMYYYY (Day-Month-Year)
  - 03022026 = 3rd February 2026
  - 31122025 = 31st December 2025

### 2. Create Folder

Put all CSV files in a folder named:
```
branch_{your_branch_id}_{DDMMYYYY}
```

**Example**:
```
branch_10000_03022026/
├── branch_10000_01_03022026.csv
├── branch_10000_02_03022026.csv
└── branch_10000_03_03022026.csv
```

### 3. Create ZIP File

Compress the folder into a ZIP file with the **same name**:
```
branch_10000_03022026.zip
```

**Important**: The ZIP must contain the folder, not just the CSV files!

**Correct ZIP structure**:
```
branch_10000_03022026.zip
└── branch_10000_03022026/
    ├── branch_10000_01_03022026.csv
    ├── branch_10000_02_03022026.csv
    └── branch_10000_03_03022026.csv
```

**Wrong ZIP structure** ❌:
```
branch_10000_03022026.zip
├── branch_10000_01_03022026.csv  ❌ No folder!
├── branch_10000_02_03022026.csv
└── branch_10000_03_03022026.csv
```

### 4. Upload ZIP File

#### Using the Provided Script

```bash
python branch_client_zip_upload.py \
    --branch-id YOUR_BRANCH_ID \
    --secret-key YOUR_SECRET_KEY \
    --csv-folder /path/to/branch_10000_03022026
```

#### Using cURL

```bash
# 1. Generate timestamp
TIMESTAMP=$(date +%s)

# 2. Generate HMAC signature (using your secret key)
# Message format: {branch_id}{zip_filename}{timestamp}
# Contact your administrator for signature generation tool

# 3. Upload
curl -X POST https://api.example.com/enterprise-upload/ \
  -H "X-Branch-ID: YOUR_BRANCH_ID" \
  -H "X-Signature: YOUR_HMAC_SIGNATURE" \
  -H "X-Timestamp: ${TIMESTAMP}" \
  -F "file=@branch_10000_03022026.zip"
```

#### Using Python requests

```python
import hmac
import hashlib
import requests
from datetime import datetime

branch_id = "10000"
secret_key = "your-secret-key"
zip_file = "branch_10000_03022026.zip"
api_url = "https://api.example.com/enterprise-upload/"

# Generate signature
timestamp = str(int(datetime.now().timestamp()))
message = f"{branch_id}{zip_file}{timestamp}"
signature = hmac.new(
    secret_key.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()

# Upload
headers = {
    'X-Branch-ID': branch_id,
    'X-Signature': signature,
    'X-Timestamp': timestamp,
}

with open(zip_file, 'rb') as f:
    files = {'file': (zip_file, f, 'application/zip')}
    response = requests.post(api_url, headers=headers, files=files)

print(response.json())
```

## CSV File Format

Your CSV files must have this header:
```
roundId;gameId;createDate;updateDate;betAmount;winAmount;status
```

**Example content**:
```csv
roundId;gameId;createDate;updateDate;betAmount;winAmount;status
R000001;G0001;2026-02-03 10:00:00;2026-02-03 10:01:00;100,50;150,75;completed
R000002;G0002;2026-02-03 10:05:00;2026-02-03 10:06:00;200,00;0,00;lost
```

**Important**:
- Use semicolon (`;`) as separator
- Decimal numbers use comma (`,`) not period
- All 7 columns required

## Limits

- **ZIP file size**: Maximum 100 MB
- **CSV files per ZIP**: Maximum 100 files
- **File naming**: Must follow exact format

## Responses

### Success (200)
```json
{
    "status": "success",
    "message": "ZIP dosyası başarıyla yüklendi. 3 CSV dosyası işlendi.",
    "folder": "branch_10000_03022026",
    "csv_count": 3
}
```

### Errors

#### Invalid ZIP filename (400)
```json
{
    "status": "error",
    "message": "ZIP dosya adı formatı hatalı. Beklenen: branch_{branch_id}_DDMMYYYY.zip"
}
```

#### Date mismatch (400)
```json
{
    "status": "error",
    "message": "CSV tarih (04022026) klasör tarihi (03022026) ile eşleşmiyor"
}
```

#### Authentication failed (403)
```json
{
    "status": "error",
    "message": "Güvenlik doğrulaması başarısız"
}
```

## Common Mistakes

### ❌ Wrong date format
```
branch_10000_01_2026-02-03.csv  ❌ Wrong! Use: 03022026
branch_10000_01_20260203.csv    ❌ Wrong! Use: 03022026
branch_10000_01_03022026.csv    ✅ Correct!
```

### ❌ Missing folder in ZIP
```
Files directly in ZIP root   ❌ Wrong!
Files in named folder         ✅ Correct!
```

### ❌ Date mismatch
```
branch_10000_03022026/
├── branch_10000_01_03022026.csv  ✅
├── branch_10000_02_04022026.csv  ❌ Different date!
```

### ❌ Wrong sequence format
```
branch_10000_1_03022026.csv   ❌ Use: 01, 02, 03
branch_10000_A1_03022026.csv  ❌ Numbers only
branch_10000_01_03022026.csv  ✅ Correct!
```

## Checklist Before Upload

- [ ] All CSV files have correct naming format
- [ ] All CSV files have the same date
- [ ] Sequence numbers are 01, 02, 03, etc.
- [ ] CSV files are in a named folder
- [ ] Folder name matches ZIP name (without .zip)
- [ ] ZIP file is under 100 MB
- [ ] CSV files have correct header row
- [ ] Decimal numbers use comma (,) not period (.)

## Need Help?

Contact your system administrator with:
1. Your branch ID
2. The error message you received
3. A sample of your file names
4. The ZIP file structure (do not send the actual data)

## Tools

### Windows - Create ZIP with Folder
```cmd
# Create folder
mkdir branch_10000_03022026

# Copy CSV files to folder
copy *.csv branch_10000_03022026\

# Create ZIP using PowerShell
powershell Compress-Archive -Path branch_10000_03022026 -DestinationPath branch_10000_03022026.zip
```

### Linux/Mac - Create ZIP with Folder
```bash
# Create folder
mkdir branch_10000_03022026

# Copy CSV files to folder
cp *.csv branch_10000_03022026/

# Create ZIP
zip -r branch_10000_03022026.zip branch_10000_03022026/
```

### Python Script
```python
import zipfile
from pathlib import Path

branch_id = "10000"
date = "03022026"
csv_folder = Path("./my_csvs")

folder_name = f"branch_{branch_id}_{date}"
zip_name = f"{folder_name}.zip"

with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for csv_file in csv_folder.glob('*.csv'):
        zipf.write(csv_file, f"{folder_name}/{csv_file.name}")

print(f"Created: {zip_name}")
```
