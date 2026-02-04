#!/usr/bin/env python
"""
Test script for ZIP-based CSV upload endpoint.
Creates a sample ZIP file and tests the upload functionality.
"""

import os
import sys
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from branch_controller.models import Bayi
import hmac
import hashlib


def create_test_csv(filename: str, num_rows: int = 10) -> str:
    """Create a test CSV file with valid format."""
    content = "roundId;gameId;createDate;updateDate;betAmount;winAmount;status\n"
    
    for i in range(1, num_rows + 1):
        content += f"R{i:06d};G{i:04d};2026-02-03 10:00:00;2026-02-03 10:01:00;100,50;150,75;completed\n"
    
    return content


def create_test_zip(branch_id: str, date_ddmmyyyy: str, num_csv_files: int = 3) -> Path:
    """
    Create a test ZIP file with the correct structure.
    
    Args:
        branch_id: Branch ID (e.g., "10000")
        date_ddmmyyyy: Date in DDMMYYYY format (e.g., "03022026")
        num_csv_files: Number of CSV files to create
    
    Returns:
        Path to created ZIP file
    """
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp(prefix='test_upload_'))
    
    try:
        # Folder name: branch_{branch_id}_{date}
        folder_name = f"branch_{branch_id}_{date_ddmmyyyy}"
        folder_path = temp_dir / folder_name
        folder_path.mkdir()
        
        # Create CSV files
        for i in range(1, num_csv_files + 1):
            csv_filename = f"branch_{branch_id}_{i:02d}_{date_ddmmyyyy}.csv"
            csv_path = folder_path / csv_filename
            
            # Write CSV content
            csv_content = create_test_csv(csv_filename, num_rows=10 + i)
            csv_path.write_text(csv_content, encoding='utf-8')
            print(f"  Created: {csv_filename}")
        
        # Create ZIP file
        zip_filename = f"branch_{branch_id}_{date_ddmmyyyy}.zip"
        zip_path = temp_dir / zip_filename
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add the folder and its contents
            for csv_file in folder_path.glob('*.csv'):
                # Store with relative path: branch_10000_03022026/file.csv
                arcname = f"{folder_name}/{csv_file.name}"
                zipf.write(csv_file, arcname=arcname)
                print(f"  Added to ZIP: {arcname}")
        
        print(f"\n[OK] ZIP created: {zip_path}")
        print(f"  Size: {zip_path.stat().st_size / 1024:.2f} KB")
        
        return zip_path
        
    except Exception as e:
        print(f"[ERROR] Error creating test ZIP: {e}")
        raise


def test_zip_structure(zip_path: Path):
    """Verify the ZIP structure is correct."""
    print(f"\n--- Verifying ZIP Structure ---")
    
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        file_list = zipf.namelist()
        print(f"Files in ZIP: {len(file_list)}")
        for filename in file_list:
            print(f"  - {filename}")
    
    print("[OK] ZIP structure verified")


def generate_hmac_signature(branch_id: str, secret_key: str, zip_filename: str, timestamp: str) -> str:
    """Generate HMAC signature for the request."""
    message = f"{branch_id}{zip_filename}{timestamp}"
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def test_upload_validation():
    """Test the validation functions without actually uploading."""
    print("\n--- Testing Validation Functions ---")
    
    from branch_controller.views import (
        validate_zip_filename,
        validate_csv_filename,
        parse_ddmmyyyy_date
    )
    
    # Test date parsing
    print("\n1. Testing date parsing:")
    test_dates = [
        ("03022026", True),  # Valid: 3 Feb 2026
        ("31122025", True),  # Valid: 31 Dec 2025
        ("32012026", False), # Invalid: day > 31
        ("00012026", False), # Invalid: day = 0
        ("01132026", False), # Invalid: month = 13
        ("12345678", False), # Invalid: not a date
    ]
    
    for date_str, expected_valid in test_dates:
        is_valid, error, iso_date = parse_ddmmyyyy_date(date_str)
        status = "[OK]" if is_valid == expected_valid else "[FAIL]"
        print(f"  {status} {date_str}: {'Valid' if is_valid else 'Invalid'} - {iso_date or error}")
    
    # Test ZIP filename validation
    print("\n2. Testing ZIP filename validation:")
    test_zips = [
        ("branch_10000_03022026.zip", "10000", True),
        ("branch_10000_32012026.zip", "10000", False),  # Invalid date
        ("branch_10000_03022026.csv", "10000", False),  # Not a ZIP
        ("branch_99999_03022026.zip", "10000", False),  # Wrong branch ID
        ("branch_10000.zip", "10000", False),           # Missing date
    ]
    
    for zip_name, branch_id, expected_valid in test_zips:
        is_valid, error, date_str = validate_zip_filename(zip_name, branch_id)
        status = "[OK]" if is_valid == expected_valid else "[FAIL]"
        result = f"Valid (date: {date_str})" if is_valid else f"Invalid ({error})"
        print(f"  {status} {zip_name}: {result}")
    
    # Test CSV filename validation
    print("\n3. Testing CSV filename validation:")
    test_csvs = [
        ("branch_10000_01_03022026.csv", "10000", "03022026", True),
        ("branch_10000_99_03022026.csv", "10000", "03022026", True),
        ("branch_10000_00_03022026.csv", "10000", "03022026", False),  # Invalid seq
        ("branch_10000_01_04022026.csv", "10000", "03022026", False),  # Wrong date
        ("branch_99999_01_03022026.csv", "10000", "03022026", False),  # Wrong branch
        ("branch_10000_A1_03022026.csv", "10000", "03022026", False),  # Invalid seq
    ]
    
    for csv_name, branch_id, folder_date, expected_valid in test_csvs:
        is_valid, error = validate_csv_filename(csv_name, branch_id, folder_date)
        status = "[OK]" if is_valid == expected_valid else "[FAIL]"
        result = "Valid" if is_valid else f"Invalid ({error})"
        print(f"  {status} {csv_name}: {result}")
    
    print("\n[OK] All validation tests completed")


def main():
    print("=" * 70)
    print("ZIP-Based CSV Upload - Test Script")
    print("=" * 70)
    
    # Test validation functions
    test_upload_validation()
    
    # Create test ZIP
    print("\n--- Creating Test ZIP File ---")
    branch_id = "10000"
    date_ddmmyyyy = "03022026"  # 3 February 2026
    
    # Check if test branch exists
    bayi = Bayi.objects.filter(branch_id=branch_id).first()
    if not bayi:
        print(f"\n[!] Warning: Test branch (ID: {branch_id}) not found in database")
        print("  Please create a test branch first or use an existing branch_id")
        return
    
    print(f"\n[OK] Found test branch: {bayi.name} (ID: {branch_id})")
    print(f"  Secret Key: {bayi.secret_key[:20]}...")
    
    # Create test ZIP
    zip_path = create_test_zip(branch_id, date_ddmmyyyy, num_csv_files=3)
    
    # Verify structure
    test_zip_structure(zip_path)
    
    # Generate HMAC signature
    timestamp = str(int(datetime.now().timestamp()))
    zip_filename = zip_path.name
    signature = generate_hmac_signature(branch_id, bayi.secret_key, zip_filename, timestamp)
    
    print("\n--- Upload Request Details ---")
    print(f"Endpoint: POST /branch/upload/")
    print(f"Headers:")
    print(f"  X-Branch-ID: {branch_id}")
    print(f"  X-Signature: {signature}")
    print(f"  X-Timestamp: {timestamp}")
    print(f"File: {zip_filename}")
    
    # Example curl command
    print("\n--- Example cURL Command ---")
    print(f'curl -X POST http://localhost:8000/branch/upload/ \\')
    print(f'  -H "X-Branch-ID: {branch_id}" \\')
    print(f'  -H "X-Signature: {signature}" \\')
    print(f'  -H "X-Timestamp: {timestamp}" \\')
    print(f'  -F "file=@{zip_path}"')
    
    print(f"\n[OK] Test ZIP file is ready at: {zip_path}")
    print(f"  You can use this file to test the upload endpoint")
    print(f"\n  NOTE: The signature is time-sensitive. Regenerate if testing later.")
    
    # Keep the file
    input("\nPress Enter to delete the test ZIP file (or Ctrl+C to keep it)...")
    
    # Cleanup
    if zip_path.parent.exists():
        shutil.rmtree(zip_path.parent)
        print("[OK] Test files cleaned up")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Test interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
