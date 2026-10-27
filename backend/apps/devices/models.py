"""Device, Credential, and EnrollmentToken models adhering to §7.2."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Optional
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.common.models import BaseTimestampedModel, BaseUUIDModel
from apps.tenancy.models import Membership, Tenant, TenantModel


class DeviceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class Device(TenantModel):
    """Enrolled laptop device (§7.2).

    Tenant ID is immutable and derived from the enrollment token.
    """

    membership = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devices",
        db_index=True,
    )
    hostname = models.CharField(max_length=255, db_index=True)
    os = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=DeviceStatus.choices,
        default=DeviceStatus.ACTIVE,
        db_index=True,
    )
    agent_version = models.CharField(max_length=64, default="", blank=True)
    hardware_id = models.CharField(max_length=255, blank=True, db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "devices"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "hostname"]),
        ]

    def __str__(self) -> str:
        return f"{self.hostname} ({self.os}) - {self.status}"

    @property
    def is_active(self) -> bool:
        return self.status == DeviceStatus.ACTIVE

    def revoke(self, actor: Optional[User] = None) -> None:
        """Immediately revokes this device and invalidates all agent credentials (E24, E38)."""
        self.status = DeviceStatus.REVOKED
        self.save(update_fields=["status", "updated_at"])

        # Revoke all credentials
        self.credentials.filter(status=CredentialStatus.ACTIVE).update(
            status=CredentialStatus.REVOKED
        )

        try:
            from apps.audit.services import log_audit_event
            log_audit_event(
                tenant=self.tenant,
                actor=actor,
                action="device.revoked",
                resource_type="device",
                resource_id=str(self.id),
                metadata={"hostname": self.hostname, "revoked_at": timezone.now().isoformat()},
            )
        except Exception:
            pass

    def reassign(self, new_membership: Optional[Membership], actor: Optional[User] = None) -> None:
        """Reassigns device to a new employee membership (E98)."""
        old_membership_id = str(self.membership_id) if self.membership_id else None
        self.membership = new_membership
        self.save(update_fields=["membership", "updated_at"])

        try:
            from apps.audit.services import log_audit_event
            log_audit_event(
                tenant=self.tenant,
                actor=actor,
                action="device.reassigned",
                resource_type="device",
                resource_id=str(self.id),
                metadata={
                    "old_membership_id": old_membership_id,
                    "new_membership_id": str(new_membership.id) if new_membership else None,
                },
            )
        except Exception:
            pass


class CredentialStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


class AgentCredential(BaseUUIDModel):
    """Cryptographic credential binding a device to the server (§7.2, E40).

    Uses a hashed rotating secret (SHA-256) per-device. Universal secrets are strictly forbidden.
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="credentials",
        db_index=True,
    )
    public_key = models.TextField(blank=True, default="")
    secret_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=CredentialStatus.choices,
        default=CredentialStatus.ACTIVE,
        db_index=True,
    )
    expires_at = models.DateTimeField(db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_credentials"
        ordering = ["-created_at"]

    @classmethod
    def create_secret_credential(
        cls,
        device: Device,
        lifetime_days: int = 90,
    ) -> tuple[AgentCredential, str]:
        raw_secret = secrets.token_urlsafe(32)
        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        expires_at = timezone.now() + timezone.timedelta(days=lifetime_days)

        cred = cls.objects.create(
            device=device,
            secret_hash=secret_hash,
            status=CredentialStatus.ACTIVE,
            expires_at=expires_at,
        )
        return cred, raw_secret

    @property
    def is_valid(self) -> bool:
        if self.status != CredentialStatus.ACTIVE:
            return False
        if self.expires_at <= timezone.now():
            return False
        return True


class EnrollmentToken(TenantModel):
    """Scoped, expiring enrollment token for onboarding devices (§8.2, E39).

    Stored hashed; never logged in plaintext.
    """

    membership = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrollment_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.IntegerField(default=1)
    use_count = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_enrollment_tokens",
    )

    class Meta:
        db_table = "enrollment_tokens"
        ordering = ["-created_at"]

    @classmethod
    def create_token(
        cls,
        tenant: Tenant,
        created_by: User,
        membership: Optional[Membership] = None,
        expires_hours: int = 24,
        max_uses: int = 1,
    ) -> tuple[EnrollmentToken, str]:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = timezone.now() + timezone.timedelta(hours=expires_hours)

        token_obj = cls.objects.create(
            tenant=tenant,
            membership=membership,
            created_by=created_by,
            token_hash=token_hash,
            expires_at=expires_at,
            max_uses=max_uses,
        )
        return token_obj, raw_token

    @property
    def is_valid(self) -> bool:
        if self.expires_at <= timezone.now():
            return False
        if self.use_count >= self.max_uses:
            return False
        return True
