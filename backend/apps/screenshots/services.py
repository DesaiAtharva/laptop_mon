"""Screenshot service layer strictly adhering to §6.2, §10, §11.2, and edge cases E49–E55, E90."""
from __future__ import annotations

import datetime
import hashlib
import io
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.audit.services import log_audit_event
from apps.devices.models import Device, DeviceStatus
from apps.policies.models import MonitoringPolicy
from apps.rbac.permissions import get_manager_accessible_team_ids
from apps.screenshots.models import (
    LegalHoldRecord,
    Screenshot,
    ScreenshotStatus,
    ScreenshotUploadIntent,
)
from apps.screenshots.storage import (
    generate_screenshot_object_key,
    generate_thumbnail_object_key,
    get_storage_backend,
)
from apps.tenancy.models import Membership, MembershipRole, Tenant, TenantStatus

logger = logging.getLogger(__name__)

# Security limit against decompression bombs (§10.2, E50)
Image.MAX_IMAGE_PIXELS = 35_000_000

# Known malware test signature strings / magic bytes (§10.2, E50)
MALWARE_SIGNATURES = [
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
    b"MZ\x90\x00",  # DOS / Windows executable magic
    b"\x7fELF",     # Linux executable magic
]


class ScreenshotServiceError(Exception):
    """Base exception for screenshot service errors."""
    pass


class ImageValidationError(ScreenshotServiceError):
    """Raised when an untrusted uploaded image fails format, dimension, or malware checks (E50)."""
    pass


class ChecksumMismatchError(ScreenshotServiceError):
    """Raised when uploaded file checksum does not match reported checksum (REQ-10-3)."""
    pass


def scan_for_malware(raw_bytes: bytes) -> None:
    """Malware scan hook verifying untrusted uploads (§10.2, E50)."""
    for sig in MALWARE_SIGNATURES:
        if sig in raw_bytes[:1024] or sig in raw_bytes:
            raise ImageValidationError("Malicious content detected: suspicious executable or malware signature.")


def verify_and_process_image(
    raw_bytes: bytes,
    expected_checksum: Optional[str] = None,
) -> Tuple[int, int, bytes]:
    """Strictly validates untrusted uploaded image using Pillow (§10.2, REQ-10-3, E50).
    
    Returns:
        (width, height, thumbnail_bytes_webp)
    """
    max_size = getattr(settings, "SCREENSHOT_MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)
    if len(raw_bytes) > max_size:
        raise ImageValidationError(f"File size {len(raw_bytes)} bytes exceeds maximum {max_size} bytes.")

    scan_for_malware(raw_bytes)

    if expected_checksum:
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        md5_hash = hashlib.md5(raw_bytes).hexdigest()
        clean_expected = expected_checksum.lower().strip()
        if clean_expected not in (sha256_hash, md5_hash):
            raise ChecksumMismatchError(
                f"Checksum mismatch: expected '{clean_expected}', computed sha256='{sha256_hash}'."
            )

    try:
        bio = io.BytesIO(raw_bytes)
        with Image.open(bio) as img:
            img.verify()

        bio.seek(0)
        with Image.open(bio) as img:
            format_name = (img.format or "").upper()
            if format_name not in ("JPEG", "WEBP"):
                raise ImageValidationError(
                    f"Unsupported image format: {format_name}. Only JPEG and WebP are accepted."
                )

            width, height = img.size
            max_w = getattr(settings, "SCREENSHOT_MAX_WIDTH", 7680)
            max_h = getattr(settings, "SCREENSHOT_MAX_HEIGHT", 4320)
            if width <= 0 or height <= 0:
                raise ImageValidationError("Invalid image dimensions (<= 0).")
            if width > max_w or height > max_h:
                raise ImageValidationError(
                    f"Image dimensions {width}x{height} exceed limits ({max_w}x{max_h})."
                )

            # Generate thumbnail WebP derivative (§10.2) with JPEG fallback
            thumbnail_bytes = b""
            try:
                thumb_img = img.copy()
                thumb_img.thumbnail((320, 180))
                thumb_bio = io.BytesIO()
                try:
                    thumb_img.save(thumb_bio, format="WEBP", quality=75)
                except Exception:
                    thumb_bio = io.BytesIO()
                    if thumb_img.mode in ("RGBA", "P"):
                        thumb_img = thumb_img.convert("RGB")
                    thumb_img.save(thumb_bio, format="JPEG", quality=75)
                thumbnail_bytes = thumb_bio.getvalue()
            except Exception as ex:
                logger.warning("Thumbnail generation error (using fallback): %s", ex)

            return width, height, thumbnail_bytes

    except (ImageValidationError, ChecksumMismatchError):
        raise
    except Exception as e:
        raise ImageValidationError(f"Failed to safely decode untrusted image: {str(e)}")


def create_upload_intent(
    device: Device,
    screenshot_id: uuid.UUID,
    captured_at: datetime.datetime,
    policy_version: int,
    content_type: str,
    file_size: int,
) -> Dict[str, Any]:
    """Generates scoped, expiring upload authorization for one object (§6.2, E51–E53)."""
    if device.status != DeviceStatus.ACTIVE:
        raise PermissionDenied("Device is revoked or inactive.")
    if device.tenant.status != TenantStatus.ACTIVE:
        raise PermissionDenied("Tenant is suspended or inactive.")

    clean_content_type = content_type.lower().strip()
    if clean_content_type not in ("image/jpeg", "image/webp"):
        raise ImageValidationError(f"Unsupported content type: {content_type}. Must be image/jpeg or image/webp.")

    max_size = getattr(settings, "SCREENSHOT_MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)
    if file_size > max_size:
        raise ImageValidationError(f"File size {file_size} exceeds limit {max_size}.")

    storage = get_storage_backend()
    ext = "webp" if "webp" in clean_content_type else "jpg"

    with transaction.atomic():
        existing_screenshot = (
            Screenshot.objects.filter(id=screenshot_id, device=device)
            .select_for_update()
            .first()
        )

        if existing_screenshot:
            # E53: If already finalized, return idempotent complete state
            if existing_screenshot.status == ScreenshotStatus.FINALIZED:
                return {
                    "status": "already_finalized",
                    "screenshot_id": str(existing_screenshot.id),
                    "object_key": existing_screenshot.object_key,
                }

            # E51: If pending, generate a fresh intent so retried uploads always get active URLs
            expires_in = getattr(settings, "SCREENSHOT_UPLOAD_INTENT_EXPIRY_SECONDS", 900)
            upload_auth = storage.generate_presigned_upload_url(
                object_key=existing_screenshot.object_key,
                content_type=clean_content_type,
                expires_in=expires_in,
            )
            expires_at = timezone.now() + datetime.timedelta(seconds=expires_in)
            new_intent = ScreenshotUploadIntent.objects.create(
                screenshot=existing_screenshot,
                device=device,
                tenant=device.tenant,
                upload_url=upload_auth["upload_url"],
                expires_at=expires_at,
            )
            return {
                "status": "pending",
                "screenshot_id": str(existing_screenshot.id),
                "upload_url": new_intent.upload_url,
                "object_key": existing_screenshot.object_key,
                "expires_at": new_intent.expires_at.isoformat(),
            }

            # Generate fresh intent for same screenshot
            expires_in = getattr(settings, "SCREENSHOT_UPLOAD_INTENT_EXPIRY_SECONDS", 900)
            upload_auth = storage.generate_presigned_upload_url(
                object_key=existing_screenshot.object_key,
                content_type=clean_content_type,
                expires_in=expires_in,
            )
            expires_at = timezone.now() + datetime.timedelta(seconds=expires_in)
            new_intent = ScreenshotUploadIntent.objects.create(
                screenshot=existing_screenshot,
                device=device,
                tenant=device.tenant,
                upload_url=upload_auth["upload_url"],
                expires_at=expires_at,
            )
            return {
                "status": "pending",
                "screenshot_id": str(existing_screenshot.id),
                "upload_url": new_intent.upload_url,
                "object_key": existing_screenshot.object_key,
                "expires_at": new_intent.expires_at.isoformat(),
            }

        # Create new Screenshot record
        policy = (
            MonitoringPolicy.objects.filter(tenant=device.tenant, version=policy_version).first()
            or MonitoringPolicy.objects.filter(tenant=device.tenant).order_by("-version").first()
        )
        retention_days = policy.retention_days if policy else 30
        delete_after = captured_at + datetime.timedelta(days=retention_days)

        object_key = generate_screenshot_object_key(
            tenant_id=device.tenant_id,
            device_id=device.id,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            extension=ext,
        )

        screenshot = Screenshot.objects.create(
            id=screenshot_id,
            device=device,
            tenant=device.tenant,
            status=ScreenshotStatus.PENDING,
            object_key=object_key,
            captured_at=captured_at,
            policy_version=policy_version,
            delete_after=delete_after,
            file_size=file_size,
        )

        expires_in = getattr(settings, "SCREENSHOT_UPLOAD_INTENT_EXPIRY_SECONDS", 900)
        upload_auth = storage.generate_presigned_upload_url(
            object_key=object_key,
            content_type=clean_content_type,
            expires_in=expires_in,
        )
        expires_at = timezone.now() + datetime.timedelta(seconds=expires_in)

        intent = ScreenshotUploadIntent.objects.create(
            screenshot=screenshot,
            device=device,
            tenant=device.tenant,
            upload_url=upload_auth["upload_url"],
            expires_at=expires_at,
        )

        return {
            "status": "pending",
            "screenshot_id": str(screenshot.id),
            "upload_url": intent.upload_url,
            "object_key": object_key,
            "expires_at": intent.expires_at.isoformat(),
        }


@transaction.atomic
def complete_screenshot_upload(
    device: Device,
    screenshot_id: uuid.UUID,
    checksum: str,
    file_size: int,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    """Completes and finalizes a two-phase screenshot upload (§6.2, E52, E53)."""
    screenshot = (
        Screenshot.objects.filter(id=screenshot_id, device=device)
        .select_for_update()
        .first()
    )
    if not screenshot:
        raise ScreenshotServiceError("Screenshot record not found for device.")

    # E53: Idempotent response if already finalized
    if screenshot.status == ScreenshotStatus.FINALIZED:
        return {
            "status": "finalized",
            "screenshot_id": str(screenshot.id),
            "object_key": screenshot.object_key,
            "thumbnail_key": screenshot.thumbnail_key,
        }

    if screenshot.status == ScreenshotStatus.DELETED:
        raise ScreenshotServiceError("Screenshot has already been deleted.")

    storage = get_storage_backend()
    if not storage.object_exists(screenshot.object_key):
        raise ScreenshotServiceError(
            f"Object {screenshot.object_key} does not exist in object storage. Upload must precede finalize."
        )

    raw_bytes = storage.get_object_bytes(screenshot.object_key)

    # Untrusted validation (E50)
    actual_width, actual_height, thumb_bytes = verify_and_process_image(
        raw_bytes=raw_bytes,
        expected_checksum=checksum,
    )

    # Save thumbnail derivative
    thumbnail_key = ""
    if thumb_bytes:
        try:
            thumbnail_key = generate_thumbnail_object_key(
                tenant_id=device.tenant_id,
                device_id=device.id,
                screenshot_id=screenshot.id,
                captured_at=screenshot.captured_at,
            )
            storage.put_object_bytes(thumbnail_key, thumb_bytes, content_type="image/webp")
        except Exception as ex:
            logger.warning("Could not persist thumbnail derivative: %s", ex)
            thumbnail_key = ""

    # Update screenshot metadata
    screenshot.thumbnail_key = thumbnail_key
    screenshot.file_size = len(raw_bytes)
    screenshot.checksum = checksum
    screenshot.width = actual_width
    screenshot.height = actual_height
    screenshot.transition_to(ScreenshotStatus.FINALIZED, save=False)
    screenshot.save(
        update_fields=[
            "status",
            "thumbnail_key",
            "file_size",
            "checksum",
            "width",
            "height",
            "updated_at",
        ]
    )

    # Consume active intents
    ScreenshotUploadIntent.objects.filter(screenshot=screenshot, consumed=False).update(
        consumed=True
    )

    return {
        "status": "finalized",
        "screenshot_id": str(screenshot.id),
        "object_key": screenshot.object_key,
        "thumbnail_key": screenshot.thumbnail_key,
    }


def generate_screenshot_view_url(
    screenshot_id: uuid.UUID,
    membership: Membership,
    request_user: User,
    request_id: str = "",
) -> Dict[str, Any]:
    """Generates short-lived, single-object presigned view URL (§10.2, REQ-10-4, E49).
    
    URL is strictly NEVER logged in database, audit logs, or error logs.
    """
    screenshot = (
        Screenshot.objects.for_tenant(membership.tenant)
        .filter(id=screenshot_id)
        .first()
    )
    if not screenshot:
        raise ScreenshotServiceError("Screenshot not found.")

    # Permissions check
    if not membership.has_screenshot_permission and not request_user.is_superuser:
        raise PermissionDenied("User does not have explicit screenshot access permission.")

    # Manager team scoping (§2.2, E47)
    if membership.role == MembershipRole.MANAGER:
        manager_team_ids = get_manager_accessible_team_ids(membership)
        device_membership = getattr(screenshot.device, "membership", None)
        if not device_membership or not device_membership.team_memberships.filter(team_id__in=manager_team_ids).exists():
            raise PermissionDenied("Manager cannot view screenshots outside assigned teams.")

    # Employee self-scoping
    if membership.role == MembershipRole.EMPLOYEE:
        if screenshot.device.membership_id != membership.id:
            raise PermissionDenied("Employee may only view screenshots from own devices.")

    expires_in = getattr(settings, "SCREENSHOT_VIEW_URL_EXPIRY_SECONDS", 604800)
    storage = get_storage_backend()
    view_url = storage.generate_presigned_view_url(screenshot.object_key, expires_in=expires_in)

    # Audited view (§11.1, REQ-10-4, E49)
    # Notice: view_url is NEVER included in audit metadata!
    log_audit_event(
        action="screenshot.viewed",
        resource_type="screenshot",
        resource_id=str(screenshot.id),
        actor=request_user,
        tenant=membership.tenant,
        metadata={
            "device_id": str(screenshot.device_id),
            "captured_at": screenshot.captured_at.isoformat(),
        },
        request_id=request_id,
    )

    return {
        "screenshot_id": str(screenshot.id),
        "view_url": view_url,
        "expires_in": expires_in,
    }


def run_retention_sweep(tenant: Optional[Tenant] = None) -> Dict[str, Any]:
    """Executes automated retention deletion job (§10.2, §11.2, E54).
    
    Deletes objects from storage, verifies deletion, updates status, and logs alerts on failure.
    Never marks completed before verification.
    """
    storage = get_storage_backend()
    now = timezone.now()

    qs = Screenshot.objects.filter(
        delete_after__lte=now,
        legal_hold=False,
    ).exclude(status=ScreenshotStatus.DELETED)

    if tenant:
        qs = qs.filter(tenant=tenant)

    deleted_count = 0
    failed_count = 0

    for screenshot in qs.iterator(chunk_size=100):
        try:
            # Delete primary object
            storage.delete_object(screenshot.object_key)

            # Delete thumbnail derivative if exists
            if screenshot.thumbnail_key:
                storage.delete_object(screenshot.thumbnail_key)

            # Verification check (E54)
            if not storage.verify_deletion(screenshot.object_key):
                logger.error("Retention deletion verification failed for screenshot %s", screenshot.id)
                failed_count += 1
                continue

            screenshot.transition_to(ScreenshotStatus.DELETED)
            deleted_count += 1

        except Exception as e:
            logger.error("Exception during retention deletion for screenshot %s: %s", screenshot.id, str(e))
            failed_count += 1

    # Backlog metric (§12.1, E54)
    backlog_count = Screenshot.objects.filter(
        delete_after__lte=now,
        legal_hold=False,
    ).exclude(status=ScreenshotStatus.DELETED).count()

    return {
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "backlog_count": backlog_count,
    }


def apply_legal_hold(
    tenant: Tenant,
    actor: User,
    reason: str,
    screenshot_ids: Optional[List[uuid.UUID]] = None,
    device: Optional[Device] = None,
    request_id: str = "",
) -> LegalHoldRecord:
    """Applies legal hold preventing automated retention deletion (§11.2, REQ-11-2, E90)."""
    with transaction.atomic():
        hold_record = LegalHoldRecord.objects.create(
            tenant=tenant,
            device=device,
            reason=reason,
            created_by=actor,
            is_active=True,
        )

        qs = Screenshot.objects.for_tenant(tenant)
        if device:
            qs = qs.filter(device=device)
        if screenshot_ids:
            qs = qs.filter(id__in=screenshot_ids)

        updated_count = qs.update(legal_hold=True)

        log_audit_event(
            action="screenshot.legal_hold_applied",
            resource_type="legal_hold_record",
            resource_id=str(hold_record.id),
            actor=actor,
            tenant=tenant,
            metadata={
                "reason": reason,
                "screenshots_held_count": updated_count,
                "device_id": str(device.id) if device else None,
            },
            request_id=request_id,
        )

        return hold_record


def release_legal_hold(
    tenant: Tenant,
    hold_record_id: uuid.UUID,
    actor: User,
    request_id: str = "",
) -> None:
    """Releases an existing legal hold (§11.2, E90)."""
    with transaction.atomic():
        hold_record = LegalHoldRecord.objects.for_tenant(tenant).filter(id=hold_record_id).first()
        if not hold_record:
            raise ScreenshotServiceError("Legal hold record not found.")

        hold_record.is_active = False
        hold_record.released_at = timezone.now()
        hold_record.save(update_fields=["is_active", "released_at", "updated_at"])

        # If no other active legal holds exist for the scope, release screenshots
        remaining_holds = LegalHoldRecord.objects.for_tenant(tenant).filter(is_active=True)
        if not remaining_holds.exists():
            Screenshot.objects.for_tenant(tenant).update(legal_hold=False)
        elif hold_record.device:
            if not remaining_holds.filter(device=hold_record.device).exists():
                Screenshot.objects.for_tenant(tenant).filter(device=hold_record.device).update(
                    legal_hold=False
                )

        log_audit_event(
            action="screenshot.legal_hold_released",
            resource_type="legal_hold_record",
            resource_id=str(hold_record.id),
            actor=actor,
            tenant=tenant,
            request_id=request_id,
        )


def execute_legal_deletion(
    tenant: Tenant,
    actor: User,
    reason: str,
    screenshot_ids: List[uuid.UUID],
    request_id: str = "",
) -> Dict[str, Any]:
    """Executes verified legal deletion of eligible data (§11.2, E90)."""
    storage = get_storage_backend()
    deleted_count = 0

    with transaction.atomic():
        screenshots = list(
            Screenshot.objects.for_tenant(tenant)
            .filter(id__in=screenshot_ids)
            .exclude(status=ScreenshotStatus.DELETED)
        )

        for s in screenshots:
            storage.delete_object(s.object_key)
            if s.thumbnail_key:
                storage.delete_object(s.thumbnail_key)

            if storage.verify_deletion(s.object_key):
                s.transition_to(ScreenshotStatus.DELETED)
                deleted_count += 1
            else:
                logger.error("Legal deletion verification failed for screenshot %s", s.id)

        # Audit outcome recorded WITHOUT sensitive image content (E90)
        log_audit_event(
            action="screenshot.legal_deletion",
            resource_type="screenshot",
            resource_id=str(screenshots[0].id) if screenshots else str(uuid.uuid4()),
            actor=actor,
            tenant=tenant,
            metadata={
                "reason": reason,
                "requested_count": len(screenshot_ids),
                "deleted_count": deleted_count,
            },
            request_id=request_id,
        )

    return {"deleted_count": deleted_count, "requested_count": len(screenshot_ids)}


def apply_retroactive_exclusion(
    tenant: Tenant,
    actor: User,
    app_identifier: str,
    action: str,
    policy_version: int,
    request_id: str = "",
) -> Dict[str, Any]:
    """Applies retroactive policy action on previously stored screenshots for newly excluded app (E55).
    
    Actions: 'keep', 'purge', 'flag_legal_review'
    """
    valid_actions = ("keep", "purge", "flag_legal_review")
    if action not in valid_actions:
        raise ScreenshotServiceError(f"Invalid retroactive action: {action}. Must be one of {valid_actions}.")

    qs = Screenshot.objects.for_tenant(tenant).filter(policy_version__lte=policy_version)

    processed_count = 0
    if action == "purge":
        storage = get_storage_backend()
        for s in qs.exclude(status=ScreenshotStatus.DELETED).iterator():
            storage.delete_object(s.object_key)
            if s.thumbnail_key:
                storage.delete_object(s.thumbnail_key)
            if storage.verify_deletion(s.object_key):
                s.transition_to(ScreenshotStatus.DELETED)
                processed_count += 1
    elif action == "flag_legal_review":
        processed_count = qs.update(exclusion_retroactive_action="flag_legal_review")

    log_audit_event(
        action="screenshot.retroactive_exclusion",
        resource_type="policy",
        resource_id=f"v{policy_version}",
        actor=actor,
        tenant=tenant,
        metadata={
            "app_identifier": app_identifier,
            "action": action,
            "policy_version": policy_version,
            "processed_count": processed_count,
        },
        request_id=request_id,
    )

    return {"action": action, "processed_count": processed_count}
