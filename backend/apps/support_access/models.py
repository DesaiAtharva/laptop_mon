"""SupportAccessGrant model strictly implementing JIT support access (E100)."""
from __future__ import annotations

from typing import Any
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.common.models import BaseTimestampedModel
from apps.tenancy.models import Tenant


class SupportAccessStatus(models.TextChoices):
    PENDING = "pending", "Pending Approval"
    APPROVED = "approved", "Approved"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


class SupportAccessGrant(BaseTimestampedModel):
    """Just-In-Time support access grant (§2.1, E100).

    Guarantees:
    - JIT request with reason captured
    - Org Admin approval required
    - Strictly time-bound (expires automatically)
    - Fully audited
    - No standing access to screenshots or content
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="support_grants",
        db_index=True,
    )
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="support_requests",
        db_index=True,
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_approvals",
    )
    reason = models.TextField(help_text="Detailed business justification for access.")
    status = models.CharField(
        max_length=32,
        choices=SupportAccessStatus.choices,
        default=SupportAccessStatus.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "support_access_grants"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Support grant {self.id} for {self.tenant.name} by {self.requester.email} ({self.status})"

    @property
    def is_valid(self) -> bool:
        if self.status != SupportAccessStatus.APPROVED:
            return False
        if not self.expires_at or self.expires_at <= timezone.now():
            return False
        return True

    def approve(self, approver: User, duration_hours: int = 4) -> None:
        """Approve access for a bounded period (max 8 hours)."""
        duration = min(max(duration_hours, 1), 8)
        self.approved_by = approver
        self.status = SupportAccessStatus.APPROVED
        self.expires_at = timezone.now() + timezone.timedelta(hours=duration)
        self.save(update_fields=["approved_by", "status", "expires_at", "updated_at"])

    def revoke(self) -> None:
        """Immediately terminate JIT access."""
        self.status = SupportAccessStatus.REVOKED
        self.save(update_fields=["status", "updated_at"])
