# ZIP-Based Folder Upload System - Implementation Guide

## Overview

This system allows branches to upload CSV files in a compressed ZIP format, reducing network transfer time while maintaining organized folder structure in storage.

## System Architecture

### Upload Flow

```
Branch Client -> ZIP File -> API Endpoint -> Extract & Validate -> Storage
```

1. **Branch creates ZIP**: Folders with multiple CSVs are compressed into a single ZIP
2. **Upload via API**: Single HTTP POST with ZIP file
3. **Server extracts**: ZIP extracted to temporary directory
4. **Validation**: Folder structure, filenames, and CSV contents validated
5. **Storage**: Extracted folder and files stored in organized structure
6. **Cleanup**: Temporary files removed

### File Structure

#### Upload Format (ZIP)
```
branch_10000_03022026.zip
├── branch_10000_03022026/
│   ├── branch_10000_01_03022026.csv
│   ├── branch_10000_02_03022026.csv
│   ├── branch_10000_03_03022026.csv
│   └── branch_10000_04_03022026.csv
```

#### Storage Structure
```
uploads/
└── {branch_id}/
    └── branch_{branch_id}_{DDMMYYYY}/
        ├── branch_{branch_id}_01_{DDMMYYYY}.csv
        ├── branch_{branch_id}_02_{DDMMYYYY}.csv
        └── ...
```

## File Naming Conventions

### ZIP File
- **Format**: `branch_{branch_id}_{DDMMYYYY}.zip`
- **Example**: `branch_10000_03022026.zip`
- **Date Format**: DDMMYYYY (Day-Month-Year)
  - 03022026 = 3rd February 2026

### Folder (Inside ZIP)
- **Format**: `branch_{branch_id}_{DDMMYYYY}`
- **Example**: `branch_10000_03022026`
- **Must match**: ZIP filename (without .zip extension)

### CSV Files (Inside Folder)
- **Format**: `branch_{branch_id}_{NN}_{DDMMYYYY}.csv`
- **Example**: `branch_10000_01_03022026.csv`
- **NN**: Sequence number (01-99)
- **Date**: Must match folder/ZIP date

## API Endpoint

### POST `/branch/upload/`

#### Headers
```
X-Branch-ID: {branch_id}
X-Signature: {hmac_signature}
X-Timestamp: {unix_timestamp}
```

#### Request Body
```
Content-Type: multipart/form-data
file: {zip_file}
```

#### HMAC Signature
```python
message = f"{branch_id}{zip_filename}{timestamp}"
signature = hmac.new(
    secret_key.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

#### Example cURL
```bash
curl -X POST http://localhost:8000/branch/upload/ \
  -H "X-Branch-ID: 10000" \
  -H "X-Signature: abc123..." \
  -H "X-Timestamp: 1738579200" \
  -F "file=@branch_10000_03022026.zip"
```

#### Success Response (200)
```json
{
    "status": "success",
    "message": "ZIP dosyası başarıyla yüklendi. 3 CSV dosyası işlendi.",
    "folder": "branch_10000_03022026",
    "csv_count": 3
}
```

#### Error Response (400/403/500)
```json
{
    "status": "error",
    "message": "Hata açıklaması"
}
```

## Validation Rules

### 1. ZIP File Validation
- File extension must be `.zip`
- Filename must match pattern: `branch_{branch_id}_{DDMMYYYY}.zip`
- Branch ID must match authenticated branch
- Date must be valid
- File size must be ≤ 100MB (configurable)

### 2. ZIP Contents Validation
- Must contain exactly one root folder
- Folder name must match ZIP name (without .zip)
- No path traversal attempts (`..`, absolute paths)

### 3. Folder Structure Validation
- Folder must contain only CSV files
- Maximum 100 CSV files per folder (configurable)
- All CSV filenames must follow naming convention

### 4. CSV Filename Validation
- Must match pattern: `branch_{branch_id}_{NN}_{DDMMYYYY}.csv`
- Branch ID must match folder branch ID
- Sequence number must be 01-99
- Date must match folder date

### 5. CSV Content Validation
- Must have valid header row
- Expected format: `roundId;gameId;createDate;updateDate;betAmount;winAmount;status`
- Validated before storage

### 6. Security Validation
- HMAC signature verification
- Branch authentication
- Active branch check
- File size limits
- Extraction timeout protection

## Configuration

### Settings (core/settings.py)
```python
# Storage backend
USE_LOCAL_FAKE_S3 = True  # or False for real S3
LOCAL_S3_BASE_DIR = BASE_DIR / "local_s3"
AWS_STORAGE_BUCKET_NAME = "your-bucket"

# Upload limits (branch_controller/views.py)
MAX_ZIP_SIZE_MB = 100
MAX_CSV_FILES_PER_ZIP = 100
```

## Validation Script

### Daily CSV Validation
```bash
python manage.py validate_yesterday_csvs
```

The validation script automatically:
1. Scans storage for folders matching the target date
2. Converts target date (YYYY-MM-DD) to folder format (DDMMYYYY)
3. Finds all CSV files in matching folders
4. Validates each CSV file
5. Logs results to database

### Script Options
```bash
# Validate specific date
python manage.py validate_yesterday_csvs --date=2026-02-03

# Dry run (no database writes)
python manage.py validate_yesterday_csvs --dry-run

# Specific branch only
python manage.py validate_yesterday_csvs --branch-id=10000

# Custom worker count
python manage.py validate_yesterday_csvs --workers=8
```

## Testing

### Run Test Script
```bash
python test_zip_upload.py
```

The test script:
1. Tests all validation functions
2. Creates a sample ZIP file with correct structure
3. Generates HMAC signature
4. Provides cURL command for manual testing

### Manual Testing Steps

1. **Create test branch** (if not exists):
```python
from branch_controller.models import Bayi
bayi = Bayi.objects.create(
    name="Test Branch",
    branch_id="10000",
    is_active=True
)
```

2. **Run test script**:
```bash
python test_zip_upload.py
```

3. **Copy the cURL command** from output

4. **Run cURL** to test upload

5. **Verify storage**:
```bash
# For local storage
ls local_s3/uploads/10000/branch_10000_03022026/

# Check logs
tail -f logs/csv_validation_2026-02-03.json
```

6. **Run validation**:
```bash
python manage.py validate_yesterday_csvs --date=2026-02-03
```

## Error Handling

### Common Errors

#### 1. Invalid ZIP filename
```
Error: "ZIP dosya adı formatı hatalı. Beklenen: branch_{branch_id}_DDMMYYYY.zip"
Fix: Ensure filename matches pattern exactly
```

#### 2. Date mismatch
```
Error: "CSV tarih (04022026) klasör tarihi (03022026) ile eşleşmiyor"
Fix: All CSV files must have same date as folder/ZIP
```

#### 3. Invalid folder structure
```
Error: "ZIP içinde tek bir klasör olmalı"
Fix: ZIP must contain exactly one root folder
```

#### 4. CSV format error
```
Error: "CSV format hataları: branch_10000_01_03022026.csv: Header'lar beklenen formatta değil"
Fix: Check CSV headers match expected format
```

#### 5. HMAC signature failed
```
Error: "Güvenlik doğrulaması başarısız"
Fix: Regenerate signature with correct message format and secret key
```

## Implementation Files

### Modified Files
1. **branch_controller/views.py**
   - Added ZIP validation functions
   - Rewritten `enterprise_upload()` endpoint
   - Added folder extraction and validation

2. **branch_controller/management/commands/validate_yesterday_csvs.py**
   - Updated `_find_csv_files()` method
   - Now scans folder structure instead of date directories

### New Files
1. **test_zip_upload.py**
   - Test script for validation functions
   - Creates sample ZIP files
   - Generates test data

2. **ZIP_UPLOAD_IMPLEMENTATION.md**
   - This documentation file

## Migration from Old System

### Old System
- Individual CSV files uploaded separately
- Filename: `branch_{branch_id}_{date}.csv`
- Storage: `uploads/{branch_id}/{filename}.csv`

### New System
- Multiple CSVs in ZIP file
- Filename: `branch_{branch_id}_{DDMMYYYY}.zip`
- Storage: `uploads/{branch_id}/branch_{branch_id}_{DDMMYYYY}/{csvs}`

### Migration Steps
No database migration needed. The system can coexist with old uploads if needed.

## Performance Benefits

1. **Network Transfer**: 60-80% reduction with ZIP compression
2. **Upload Speed**: Single request vs multiple requests
3. **Reliability**: Atomic operation - all files or none
4. **Organization**: Better folder structure for management

## Security Features

1. **HMAC Authentication**: Prevents unauthorized uploads
2. **Path Traversal Protection**: Validates ZIP contents
3. **File Size Limits**: Prevents DoS attacks
4. **Extraction Timeout**: Protects against zip bombs
5. **Input Validation**: Multiple layers of validation
6. **Secure Cleanup**: Temporary files always cleaned up

## Troubleshooting

### Check Logs
```python
# TransferLog entries
from branch_controller.models import TransferLog
TransferLog.objects.filter(filename__contains='.zip').order_by('-created_at')[:10]

# CSV Validation results
from branch_controller.models import CSVValidationError
CSVValidationError.objects.filter(validation_date='2026-02-03')
```

### Debug Mode
Add debug prints in `views.py`:
```python
print(f"[DEBUG] Extracted folder: {folder_name}")
print(f"[DEBUG] CSV files found: {len(csv_files)}")
```

### Storage Check
```bash
# Local storage
tree local_s3/uploads/

# S3 storage
aws s3 ls s3://your-bucket/uploads/ --recursive
```

## Support

For issues or questions:
1. Check this documentation
2. Run test script: `python test_zip_upload.py`
3. Review logs: `logs/csv_validation_*.json`
4. Check TransferLog in Django admin
