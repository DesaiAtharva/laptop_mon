"""Screenshot models adhering to §7.2, §10, and §11.2."""
from __future__ import annotations

import uuid
from typing import Any
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.common.models import BaseUUIDModel
from apps.devices.models import Device
from apps.tenancy.models import TenantModel


class InvalidStatusTransitionError(Exception):
    """Raised when an invalid screenshot lifecycle transition is attempted."""
    pass


class ScreenshotStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADED = "uploaded", "Uploaded"
    FINALIZED = "finalized", "Finalized"
    FAILED = "failed", "Failed"
    DELETED = "deleted", "Deleted"


VALID_STATUS_TRANSITIONS = {
    ScreenshotStatus.PENDING: {
        ScreenshotStatus.UPLOADED,
        ScreenshotStatus.FINALIZED,
        ScreenshotStatus.FAILED,
        ScreenshotStatus.DELETED,
    },
    ScreenshotStatus.UPLOADED: {
        ScreenshotStatus.FINALIZED,
        ScreenshotStatus.FAILED,
        ScreenshotStatus.DELETED,
    },
    ScreenshotStatus.FINALIZED: {
        ScreenshotStatus.DELETED,
    },
    ScreenshotStatus.FAILED: {
        ScreenshotStatus.DELETED,
    },
    ScreenshotStatus.DELETED: set(),
}


class Screenshot(TenantModel):
    """Screenshot metadata record (§7.2, §10.2).
    
    CRITICAL RULE (REQ-10-1):
    Image bytes MUST NEVER be stored in MySQL — only object keys.
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="screenshots",
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=ScreenshotStatus.choices,
        default=ScreenshotStatus.PENDING,
        db_index=True,
    )
    object_key = models.CharField(
        max_length=512,
        db_index=True,
        help_text="Tenant-scoped non-guessable private S3 object key (REQ-10-2).",
    )
    thumbnail_key = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Object key for thumbnail derivative (§10.2).",
    )
    captured_at = models.DateTimeField(db_index=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes.",
    )
    checksum = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Client and server verified checksum (SHA-256 or MD5).",
    )
    policy_version = models.PositiveIntegerField(default=1)
    delete_after = models.DateTimeField(
        db_index=True,
        help_text="Retention horizon: delete_after = captured_at + policy.retention_days (REQ-11-2).",
    )
    legal_hold = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Legal hold flag preventing automated retention deletion (REQ-11-2, E90).",
    )
    exclusion_retroactive_action = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Status of retroactive handling if captured app was newly excluded (E55).",
    )

    class Meta:
        db_table = "screenshots"
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["tenant", "captured_at"]),
            models.Index(fields=["device", "captured_at"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["delete_after", "legal_hold"]),
        ]

    def __str__(self) -> str:
        return f"Screenshot {self.id} for {self.device} [{self.status}]"

    def can_transition_to(self, new_status: str) -> bool:
        """Returns True if transition from current status to new_status is permitted."""
        return new_status in VALID_STATUS_TRANSITIONS.get(ScreenshotStatus(self.status), set())

    def transition_to(self, new_status: str, save: bool = True) -> None:
        """Transitions to new status or raises InvalidStatusTransitionError."""
        if self.status == new_status:
            return  # Idempotent no-op
        if not self.can_transition_to(new_status):
            raise InvalidStatusTransitionError(
                f"Cannot transition screenshot {self.id} from {self.status} to {new_status}."
            )
        self.status = new_status
        if save:
            self.save(update_fields=["status", "updated_at"])


class ScreenshotUploadIntent(TenantModel):
    """Tracks expiring upload authorizations for two-phase screenshot upload protocol (§6.2, E51)."""

    screenshot = models.ForeignKey(
        Screenshot,
        on_delete=models.CASCADE,
        related_name="upload_intents",
        db_index=True,
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="screenshot_upload_intents",
        db_index=True,
    )
    upload_url = models.TextField(help_text="Presigned upload authorization URL.")
    expires_at = models.DateTimeField(db_index=True)
    consumed = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "screenshot_upload_intents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["screenshot", "consumed"]),
            models.Index(fields=["expires_at", "consumed"]),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at


class LegalHoldRecord(TenantModel):
    """Tracks legal holds placed on tenant data to prevent automated retention deletion (§11.2, E90)."""

    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legal_holds",
    )
    reason = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_legal_holds",
    )
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "legal_hold_records"
        ordering = ["-created_at"]
