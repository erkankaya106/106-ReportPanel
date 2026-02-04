import hashlib
import hmac
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import Bayi, TransferLog


def make_signature(branch_id: str, secret_key: str, filename: str, timestamp: str) -> str:
    """
    Gerçek bir bayi script'inde olduğu gibi HMAC imzası üretir.
    message = f\"{branch_id}{filename}{timestamp}\"
    """
    message = f"{branch_id}{filename}{timestamp}"
    return hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


class BranchUploadTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.branch_id = "10000"
        self.secret_key = "test_secret_key"
        self.bayi = Bayi.objects.create(
            name="Test Bayi",
            branch_id=self.branch_id,
            secret_key=self.secret_key,
            is_active=True,
        )
        self.url = reverse("enterprise_upload")

    def _make_file(self, name: str, content: bytes | None = None) -> SimpleUploadedFile:
        if content is None:
            content = b"col1,col2\nval1,val2\n"
        return SimpleUploadedFile(name, content, content_type="text/csv")

    def _make_headers(self, branch_id: str, signature: str, timestamp: str) -> dict:
        return {
            "HTTP_X_BRANCH_ID": branch_id,
            "HTTP_X_SIGNATURE": signature,
            "HTTP_X_TIMESTAMP": timestamp,
        }

    @patch("branch_controller.views.boto3.client")
    def test_successful_upload_creates_s3_object_and_log(self, mock_boto_client):
        """
        Geçerli bayi + doğru HMAC + doğru dosya adı ile başarılı upload.
        """
        filename = f"branch_{self.branch_id}_20260128.csv"
        uploaded_file = self._make_file(filename)
        timestamp = str(int(time.time()))
        signature = make_signature(self.branch_id, self.secret_key, filename, timestamp)

        mock_s3 = mock_boto_client.return_value

        response = self.client.post(
            self.url,
            {"file": uploaded_file},
            **self._make_headers(self.branch_id, signature, timestamp),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "success")

        # S3 upload çağrıldı mı?
        mock_s3.upload_fileobj.assert_called_once()

        # TransferLog kaydı doğru mu?
        log = TransferLog.objects.latest("created_at")
        self.assertEqual(log.bayi, self.bayi)
        self.assertEqual(log.filename, filename)
        self.assertEqual(log.status, "SUCCESS")
        self.assertTrue(log.s3_path.endswith(f"/{filename}"))

    def test_get_method_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json().get("status"), "error")

    def test_missing_all_parameters_returns_400(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("status"), "error")

    def test_missing_file_returns_400(self):
        timestamp = str(int(time.time()))
        filename = f"branch_{self.branch_id}_20260128.csv"
        signature = make_signature(self.branch_id, self.secret_key, filename, timestamp)

        response = self.client.post(
            self.url,
            {},  # file yok
            **self._make_headers(self.branch_id, signature, timestamp),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("status"), "error")

    def test_invalid_or_inactive_branch_returns_403(self):
        # Pasif bayi
        self.bayi.is_active = False
        self.bayi.save()

        filename = f"branch_{self.branch_id}_20260128.csv"
        uploaded_file = self._make_file(filename)
        timestamp = str(int(time.time()))
        signature = make_signature(self.branch_id, self.secret_key, filename, timestamp)

        response = self.client.post(
            self.url,
            {"file": uploaded_file},
            **self._make_headers(self.branch_id, signature, timestamp),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("status"), "error")

        # Hiç olmayan bayi
        other_branch_id = "99999"
        filename2 = f"branch_{other_branch_id}_20260128.csv"
        uploaded_file2 = self._make_file(filename2)
        timestamp2 = str(int(time.time()))
        # Bu imza geçersiz olacak çünkü DB'de böyle bir bayi yok
        signature2 = make_signature(other_branch_id, "some_secret", filename2, timestamp2)

        response2 = self.client.post(
            self.url,
            {"file": uploaded_file2},
            **self._make_headers(other_branch_id, signature2, timestamp2),
        )
        self.assertEqual(response2.status_code, 403)
        self.assertEqual(response2.json().get("status"), "error")

    def test_wrong_hmac_signature_returns_403(self):
        filename = f"branch_{self.branch_id}_20260128.csv"
        uploaded_file = self._make_file(filename)
        timestamp = str(int(time.time()))
        # Yanlış imza
        wrong_signature = "0" * 64

        response = self.client.post(
            self.url,
            {"file": uploaded_file},
            **self._make_headers(self.branch_id, wrong_signature, timestamp),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("status"), "error")

    def test_wrong_filename_format_returns_400(self):
        bad_filename = "wrongname_20260128.csv"
        uploaded_file = self._make_file(bad_filename)
        timestamp = str(int(time.time()))
        # İmza dosya adı üzerinden hesaplandığı için yine aynı ismi kullanıyoruz
        signature = make_signature(self.branch_id, self.secret_key, bad_filename, timestamp)

        response = self.client.post(
            self.url,
            {"file": uploaded_file},
            **self._make_headers(self.branch_id, signature, timestamp),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("status"), "error")

    @patch("branch_controller.views.boto3.client")
    def test_s3_error_creates_failed_log_and_returns_500(self, mock_boto_client):
        """
        S3 upload sırasında exception atılırsa 500 dönmeli ve FAILED log oluşmalı.
        """
        filename = f"branch_{self.branch_id}_20260128.csv"
        uploaded_file = self._make_file(filename)
        timestamp = str(int(time.time()))
        signature = make_signature(self.branch_id, self.secret_key, filename, timestamp)

        mock_s3 = mock_boto_client.return_value
        mock_s3.upload_fileobj.side_effect = Exception("S3 error")

        response = self.client.post(
            self.url,
            {"file": uploaded_file},
            **self._make_headers(self.branch_id, signature, timestamp),
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json().get("status"), "error")

        log = TransferLog.objects.latest("created_at")
        self.assertEqual(log.bayi, self.bayi)
        self.assertEqual(log.filename, filename)
        self.assertEqual(log.status, "FAILED")
        self.assertIn("S3 error", log.error_message or "")
