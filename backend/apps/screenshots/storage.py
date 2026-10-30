"""Object storage abstraction and backends strictly adhering to §10.2 and REQ-10-1/REQ-10-2."""
from __future__ import annotations
 
import datetime
import hashlib
import hmac
import importlib
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse
import uuid

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_storage_prefix() -> str:
    prefix = getattr(
        settings,
        "SCREENSHOT_STORAGE_PREFIX",
        os.environ.get("SCREENSHOT_STORAGE_PREFIX", "Monitor"),
    ).strip("/")
    return f"{prefix}/" if prefix else ""


def generate_screenshot_object_key(
    tenant_id: uuid.UUID | str,
    device_id: uuid.UUID | str,
    screenshot_id: uuid.UUID | str,
    captured_at: datetime.datetime,
    extension: str = "jpg",
) -> str:
    """Generates tenant-scoped, non-guessable, date-partitioned S3 object key (§10.2, REQ-10-2)."""
    clean_ext = extension.lstrip(".").lower()
    if clean_ext not in ("jpg", "jpeg", "webp"):
        clean_ext = "jpg"
    prefix = get_storage_prefix()
    return (
        f"{prefix}tenants/{tenant_id}/devices/{device_id}/"
        f"{captured_at.year:04d}/{captured_at.month:02d}/{captured_at.day:02d}/"
        f"{screenshot_id}.{clean_ext}"
    )


def generate_thumbnail_object_key(
    tenant_id: uuid.UUID | str,
    device_id: uuid.UUID | str,
    screenshot_id: uuid.UUID | str,
    captured_at: datetime.datetime,
) -> str:
    """Generates tenant-scoped object key for thumbnail derivative (§10.2)."""
    prefix = get_storage_prefix()
    return (
        f"{prefix}tenants/{tenant_id}/devices/{device_id}/"
        f"{captured_at.year:04d}/{captured_at.month:02d}/{captured_at.day:02d}/"
        f"{screenshot_id}_thumb.webp"
    )


class BaseScreenshotStorage:
    """Abstract storage interface for screenshot objects in private S3-compatible storage."""

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires_in: int = 900
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def generate_presigned_view_url(self, object_key: str, expires_in: int = 300) -> str:
        raise NotImplementedError

    def is_view_url_expired(self, url: str) -> bool:
        raise NotImplementedError

    def object_exists(self, object_key: str) -> bool:
        raise NotImplementedError

    def get_object_metadata(self, object_key: str) -> Dict[str, Any]:
        raise NotImplementedError

    def get_object_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def put_object_bytes(
        self, object_key: str, data: bytes, content_type: str = "image/jpeg"
    ) -> None:
        raise NotImplementedError

    def delete_object(self, object_key: str) -> bool:
        raise NotImplementedError

    def verify_deletion(self, object_key: str) -> bool:
        """Verifies that an object has been durably purged from storage (§10.2, E54)."""
        return not self.object_exists(object_key)


class MemoryObjectStorageBackend(BaseScreenshotStorage):
    """In-memory object storage backend with signed tokens for deterministic testing."""

    def __init__(self) -> None:
        # object_key -> (bytes, content_type, updated_at)
        self._objects: Dict[str, Tuple[bytes, str, datetime.datetime]] = {}
        self.simulated_deletion_failure = False

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires_in: int = 900
    ) -> Dict[str, Any]:
        exp_ts = int(timezone.now().timestamp()) + expires_in
        sig = self._sign(f"{object_key}:{content_type}:{exp_ts}")
        query = urlencode(
            {"key": object_key, "type": content_type, "expires": exp_ts, "sig": sig}
        )
        upload_url = f"https://storage.internal/upload?{query}"
        return {
            "upload_url": upload_url,
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
            "expires_at": (timezone.now() + datetime.timedelta(seconds=expires_in)).isoformat(),
        }

    def generate_presigned_view_url(self, object_key: str, expires_in: int = 300) -> str:
        exp_ts = int(timezone.now().timestamp()) + expires_in
        sig = self._sign(f"view:{object_key}:{exp_ts}")
        query = urlencode({"key": object_key, "expires": exp_ts, "sig": sig})
        return f"https://storage.internal/view?{query}"

    def is_view_url_expired(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "expires" not in qs:
                return True
            exp_ts = int(qs["expires"][0])
            now_ts = int(timezone.now().timestamp())
            return now_ts > exp_ts
        except Exception:
            return True

    def object_exists(self, object_key: str) -> bool:
        return object_key in self._objects

    def get_object_metadata(self, object_key: str) -> Dict[str, Any]:
        if object_key not in self._objects:
            raise FileNotFoundError(f"Object {object_key} does not exist.")
        data, content_type, _ = self._objects[object_key]
        return {
            "content_length": len(data),
            "content_type": content_type,
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def get_object_bytes(self, object_key: str) -> bytes:
        if object_key not in self._objects:
            raise FileNotFoundError(f"Object {object_key} does not exist.")
        return self._objects[object_key][0]

    def put_object_bytes(
        self, object_key: str, data: bytes, content_type: str = "image/jpeg"
    ) -> None:
        self._objects[object_key] = (data, content_type, timezone.now())

    def delete_object(self, object_key: str) -> bool:
        if self.simulated_deletion_failure:
            logger.error("Simulated storage failure deleting %s", object_key)
            return False
        if object_key in self._objects:
            del self._objects[object_key]
            return True
        return True

    def verify_deletion(self, object_key: str) -> bool:
        if self.simulated_deletion_failure:
            return False
        return not self.object_exists(object_key)

    def _sign(self, payload: str) -> str:
        secret = getattr(settings, "SECRET_KEY", "fallback-secret").encode("utf-8")
        return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


class FileSystemObjectStorageBackend(BaseScreenshotStorage):
    """Secure on-disk object storage backend with HMAC-SHA256 signed presigned URLs."""

    def __init__(self, root_dir: Optional[str] = None) -> None:
        self.root_dir = root_dir or getattr(
            settings,
            "SCREENSHOT_STORAGE_LOCAL_DIR",
            os.path.join(getattr(settings, "MEDIA_ROOT", "/app/media"), "screenshots"),
        )
        os.makedirs(self.root_dir, exist_ok=True)

    def _get_path(self, object_key: str) -> str:
        clean_key = object_key.replace("\\", "/").lstrip("/")
        full_path = os.path.abspath(os.path.join(self.root_dir, clean_key))
        if not full_path.startswith(os.path.abspath(self.root_dir)):
            raise ValueError("Invalid object key traversal.")
        return full_path

    def _sign(self, payload: str) -> str:
        secret = getattr(settings, "SECRET_KEY", "fallback-secret").encode("utf-8")
        return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires_in: int = 900
    ) -> Dict[str, Any]:
        exp_ts = int(timezone.now().timestamp()) + expires_in
        sig = self._sign(f"upload:{object_key}:{content_type}:{exp_ts}")
        query = urlencode(
            {"key": object_key, "type": content_type, "expires": exp_ts, "sig": sig}
        )
        base_url = getattr(settings, "BACKEND_BASE_URL", "https://monitor.saptasuryasolar.com").rstrip("/")
        upload_url = f"{base_url}/api/agent/screenshots/storage-upload?{query}"
        return {
            "upload_url": upload_url,
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
            "expires_at": (timezone.now() + datetime.timedelta(seconds=expires_in)).isoformat(),
        }

    def generate_presigned_view_url(self, object_key: str, expires_in: int = 300) -> str:
        exp_ts = int(timezone.now().timestamp()) + expires_in
        sig = self._sign(f"view:{object_key}:{exp_ts}")
        query = urlencode({"key": object_key, "expires": exp_ts, "sig": sig})
        base_url = getattr(settings, "BACKEND_BASE_URL", "https://monitor.saptasuryasolar.com").rstrip("/")
        return f"{base_url}/api/screenshots/storage-view?{query}"

    def is_view_url_expired(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "expires" not in qs:
                return True
            exp_ts = int(qs["expires"][0])
            return int(timezone.now().timestamp()) > exp_ts
        except Exception:
            return True

    def object_exists(self, object_key: str) -> bool:
        return os.path.exists(self._get_path(object_key))

    def get_object_metadata(self, object_key: str) -> Dict[str, Any]:
        path = self._get_path(object_key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Object {object_key} does not exist.")
        stat = os.stat(path)
        with open(path, "rb") as f:
            data = f.read()
        return {
            "content_length": stat.st_size,
            "content_type": "image/webp" if object_key.endswith(".webp") else "image/jpeg",
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def get_object_bytes(self, object_key: str) -> bytes:
        path = self._get_path(object_key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Object {object_key} does not exist.")
        with open(path, "rb") as f:
            return f.read()

    def put_object_bytes(
        self, object_key: str, data: bytes, content_type: str = "image/jpeg"
    ) -> None:
        path = self._get_path(object_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def delete_object(self, object_key: str) -> bool:
        try:
            path = self._get_path(object_key)
            if os.path.exists(path):
                os.remove(path)
            return True
        except Exception as e:
            logger.error("Failed to delete local object %s: %s", object_key, str(e))
            return False

    def verify_deletion(self, object_key: str) -> bool:
        return not self.object_exists(object_key)


class S3ObjectStorageBackend(BaseScreenshotStorage):
    """Production S3 / MinIO backend using boto3 client with automatic fallback."""

    def __init__(self) -> None:
        import boto3
        from botocore.client import Config

        self._fallback = FileSystemObjectStorageBackend()
        self.bucket = getattr(settings, "SCREENSHOT_STORAGE_BUCKET", "laptop-mon-screenshots")
        self.endpoint_url = getattr(settings, "SCREENSHOT_STORAGE_ENDPOINT", "")
        self.access_key = (
            getattr(settings, "SCREENSHOT_STORAGE_ACCESS_KEY", "")
            or os.environ.get("AWS_ACCESS_KEY_ID", "")
        )
        self.secret_key = (
            getattr(settings, "SCREENSHOT_STORAGE_SECRET_KEY", "")
            or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        )
        self.region = (
            getattr(settings, "SCREENSHOT_STORAGE_REGION", "")
            or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )

        try:
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url if self.endpoint_url else None,
                aws_access_key_id=self.access_key if self.access_key else None,
                aws_secret_access_key=self.secret_key if self.secret_key else None,
                region_name=self.region,
                config=Config(signature_version="s3v4"),
            )
        except Exception as exc:
            logger.warning("Could not initialize S3 client: %s; using local fallback.", exc)
            self.s3_client = None

    def _is_s3_active(self) -> bool:
        return bool(self.s3_client and (self.access_key or self.endpoint_url))

    def generate_presigned_upload_url(
        self, object_key: str, content_type: str, expires_in: int = 900
    ) -> Dict[str, Any]:
        if not self._is_s3_active():
            return self._fallback.generate_presigned_upload_url(object_key, content_type, expires_in)
        try:
            url = self.s3_client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
            return {
                "upload_url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
                "expires_in": expires_in,
                "expires_at": (timezone.now() + datetime.timedelta(seconds=expires_in)).isoformat(),
            }
        except Exception as ex:
            logger.warning("S3 generate_presigned_upload_url failed (%s), using local fallback", ex)
            return self._fallback.generate_presigned_upload_url(object_key, content_type, expires_in)

    def generate_presigned_view_url(self, object_key: str, expires_in: int = 300) -> str:
        if not self._is_s3_active():
            return self._fallback.generate_presigned_view_url(object_key, expires_in)
        try:
            return str(
                self.s3_client.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={"Bucket": self.bucket, "Key": object_key},
                    ExpiresIn=expires_in,
                )
            )
        except Exception as ex:
            logger.warning("S3 generate_presigned_view_url failed (%s), using local fallback", ex)
            return self._fallback.generate_presigned_view_url(object_key, expires_in)

    def is_view_url_expired(self, url: str) -> bool:
        if "storage-view" in url:
            return self._fallback.is_view_url_expired(url)
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "X-Amz-Date" in qs and "X-Amz-Expires" in qs:
                date_str = qs["X-Amz-Date"][0]
                expires_sec = int(qs["X-Amz-Expires"][0])
                start_dt = datetime.datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=datetime.timezone.utc
                )
                return timezone.now() > start_dt + datetime.timedelta(seconds=expires_sec)
            return False
        except Exception:
            return True

    def object_exists(self, object_key: str) -> bool:
        if self._is_s3_active():
            from botocore.exceptions import ClientError
            try:
                self.s3_client.head_object(Bucket=self.bucket, Key=object_key)
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                    return False
                raise
            except Exception:
                return False
        return self._fallback.object_exists(object_key)

    def get_object_metadata(self, object_key: str) -> Dict[str, Any]:
        if self._is_s3_active():
            response = self.s3_client.head_object(Bucket=self.bucket, Key=object_key)
            return {
                "content_length": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", ""),
                "etag": response.get("ETag", "").strip('"'),
            }
        return self._fallback.get_object_metadata(object_key)

    def get_object_bytes(self, object_key: str) -> bytes:
        if self._is_s3_active():
            response = self.s3_client.get_object(Bucket=self.bucket, Key=object_key)
            body: bytes = response["Body"].read()
            return body
        return self._fallback.get_object_bytes(object_key)

    def put_object_bytes(
        self, object_key: str, data: bytes, content_type: str = "image/jpeg"
    ) -> None:
        if self._is_s3_active():
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
            )
            return
        self._fallback.put_object_bytes(object_key, data, content_type)

    def delete_object(self, object_key: str) -> bool:
        if self._is_s3_active():
            try:
                self.s3_client.delete_object(Bucket=self.bucket, Key=object_key)
                return True
            except Exception as e:
                logger.error("Failed to delete S3 object %s: %s", object_key, str(e))
                return False
        return self._fallback.delete_object(object_key)

    def verify_deletion(self, object_key: str) -> bool:
        return not self.object_exists(object_key)


_storage_backend_instance: Optional[BaseScreenshotStorage] = None


def get_storage_backend() -> BaseScreenshotStorage:
    """Returns singleton instance of the configured screenshot storage backend."""
    global _storage_backend_instance
    if _storage_backend_instance is None:
        backend_path = getattr(
            settings,
            "SCREENSHOT_STORAGE_BACKEND",
            "apps.screenshots.storage.MemoryObjectStorageBackend",
        )
        module_name, class_name = backend_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        storage_cls = getattr(module, class_name)
        _storage_backend_instance = storage_cls()
    return _storage_backend_instance


def reset_storage_backend() -> None:
    """Helper to reset storage backend instance in tests."""
    global _storage_backend_instance
    _storage_backend_instance = None
