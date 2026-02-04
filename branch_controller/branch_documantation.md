import requests
import hmac
import hashlib
import time

# Bayi Bilgileri
BRANCH_ID = "10000"
SECRET_KEY = "bayinin_ozel_keyi"
FILE_PATH = "branch_10000_20261123.csv"
URL = "https://api.seninsistemin.com/upload/"

timestamp = str(int(time.time()))
filename = "branch_10000_20261123.csv"

# İmza Oluşturma
message = f"{BRANCH_ID}{filename}{timestamp}"
signature = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()

# Gönderim
with open(FILE_PATH, 'rb') as f:
    headers = {
        'X-Branch-ID': BRANCH_ID,
        'X-Signature': signature,
        'X-Timestamp': timestamp
    }
    response = requests.post(URL, files={'file': f}, headers=headers)
    print(response.json())