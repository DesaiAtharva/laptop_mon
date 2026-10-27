"""Append-only AuditLog model strictly per §7.2 and §11.1."""
from __future__ import annotations

import uuid
from typing import Any
from django.core.exceptions import PermissionDenied
from django.db import models
from apps.accounts.models import User
from apps.common.models import BaseUUIDModel
from apps.tenancy.models import Tenant


class AuditLogQuerySet(models.QuerySet):
    """Queryset enforcing append-only behavior at the ORM level."""

    def update(self, **kwargs: Any) -> int:
        raise PermissionDenied("Audit logs are append-only and cannot be modified.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise PermissionDenied("Audit logs are append-only and cannot be deleted.")


class AuditLogManager(models.Manager):
    def get_queryset(self) -> AuditLogQuerySet:
        return AuditLogQuerySet(self.model, using=self._db)


class AuditLog(BaseUUIDModel):
    """Immutable audit trail recording every security-critical event (§7.2, §11.1).

    Enforces append-only semantics:
    - Modifications are blocked.
    - Deletions are blocked.
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="audit_logs",
        null=True,
        blank=True,
        db_index=True,
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
        db_index=True,
    )
    action = models.CharField(max_length=128, db_index=True)
    resource_type = models.CharField(max_length=64, db_index=True)
    resource_id = models.CharField(max_length=128, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditLogManager()

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["tenant", "action"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.created_at.isoformat()}] {self.action} by {self.actor_id} on {self.resource_type}:{self.resource_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding is False and AuditLog.objects.filter(pk=self.pk).exists():
            raise PermissionDenied("Audit logs are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionDenied("Audit logs are append-only and cannot be deleted.")
