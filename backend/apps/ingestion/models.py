"""WorkSession, EventBatch, and ActivityEvent models strictly per §7.2."""
from __future__ import annotations

import uuid
from typing import Any
from django.core.exceptions import PermissionDenied
from django.db import models
from apps.common.models import BaseTimestampedModel, BaseUUIDModel
from apps.devices.models import Device
from apps.tenancy.models import Tenant, TenantModel


class WorkSession(TenantModel):
    """Tracks continuous user sessions on a monitored laptop (§7.2)."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="work_sessions",
        db_index=True,
    )
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    end_reason = models.CharField(max_length=64, blank=True, default="")
    session_type = models.CharField(max_length=64, default="interactive", db_index=True)

    class Meta:
        db_table = "work_sessions"
        ordering = ["-started_at"]


class EventBatchStatus(models.TextChoices):
    ACCEPTED = "accepted", "Accepted"
    PARTIAL = "partial", "Partial"
    REJECTED = "rejected", "Rejected"


class EventBatch(TenantModel):
    """Metadata record for an uploaded batch of telemetry events (§7.2)."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="event_batches",
        db_index=True,
    )
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    agent_version = models.CharField(max_length=64)
    schema_version = models.IntegerField(default=1)
    total_events = models.IntegerField(default=0)
    accepted_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=EventBatchStatus.choices,
        default=EventBatchStatus.ACCEPTED,
        db_index=True,
    )

    class Meta:
        db_table = "event_batches"
        ordering = ["-received_at"]


class ActivityEvent(models.Model):
    """Raw accepted telemetry event from agent journal (§7.2).

    Rules:
    - ID is client-generated UUID from agent journal.
    - Immutable once written (modifications and deletions prohibited).
    """

    id = models.UUIDField(primary_key=True, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="activity_events",
        db_index=True,
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="activity_events",
        db_index=True,
    )
    batch = models.ForeignKey(
        EventBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    payload = models.JSONField(default=dict)
    upload_status = models.CharField(max_length=32, default="accepted", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activity_events"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["tenant", "device", "occurred_at"]),
            models.Index(fields=["device", "event_type", "occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"Event {self.id} ({self.event_type}) on device {self.device_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding is False and ActivityEvent.objects.filter(pk=self.pk).exists():
            raise PermissionDenied("Raw accepted events are immutable and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionDenied("Raw accepted events are immutable and cannot be deleted.")
