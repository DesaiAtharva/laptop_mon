"""Analytics models adhering strictly to §7.2, §9, and §10.3."""
from __future__ import annotations

import uuid
from typing import Any
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.devices.models import Device
from apps.policies.models import AppClassification
from apps.tenancy.models import TenantModel


class IntervalState(models.TextChoices):
    ACTIVE = "active", "Active"
    IDLE = "idle", "Idle"
    LOCKED = "locked", "Locked"
    ASLEEP = "asleep", "Asleep"
    UNOBSERVED = "unobserved", "Unobserved"
    OFFLINE = "offline", "Offline"
    UNCLASSIFIED = "unclassified", "Unclassified"
    PERMISSION_DENIED = "permission-denied", "Permission Denied"
    TELEMETRY_GAP = "telemetry-gap", "Telemetry Gap"


class ExportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    EXPIRED = "expired", "Expired"


class ExportType(models.TextChoices):
    DAILY_METRICS = "daily_metrics", "Daily Metrics"
    TIMELINE = "timeline", "Timeline Intervals"
    APP_USAGE = "app_usage", "App Usage"


class AppUsageInterval(TenantModel):
    """Normalized, non-overlapping application and state usage interval (§7.2, §9.1).
    
    Invariants:
    - No overlapping intervals per device (REQ-9-2, E73).
    - Gaps are explicit unknowns (state='telemetry-gap') — never filled (REQ-9-3).
    - Non-negative durations (duration_seconds >= 0) (REQ-9-4, E72).
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="usage_intervals",
        db_index=True,
    )
    app_identifier = models.CharField(
        max_length=255,
        db_index=True,
        default="unknown",
        help_text="Normalized app executable or process path (e.g. code.exe, chrome.exe).",
    )
    app_classification = models.CharField(
        max_length=32,
        choices=AppClassification.choices,
        default=AppClassification.NEUTRAL,
        db_index=True,
    )
    app_classification_version = models.IntegerField(default=1)
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(db_index=True)
    duration_seconds = models.FloatField(
        default=0.0,
        help_text="Duration in seconds (always >= 0).",
    )
    state = models.CharField(
        max_length=32,
        choices=IntervalState.choices,
        default=IntervalState.ACTIVE,
        db_index=True,
    )
    calc_version = models.IntegerField(
        default=1,
        db_index=True,
        help_text="Calculation engine version (REQ-9-5).",
    )
    is_inferred = models.BooleanField(
        default=False,
        help_text="True if interval was closed provisionally without an explicit end event (E71).",
    )

    class Meta:
        db_table = "app_usage_intervals"
        ordering = ["started_at"]
        indexes = [
            models.Index(fields=["tenant", "device", "started_at"]),
            models.Index(fields=["device", "calc_version", "started_at"]),
            models.Index(fields=["tenant", "started_at", "ended_at"]),
            models.Index(fields=["tenant", "state"]),
        ]

    def __str__(self) -> str:
        return f"{self.device} [{self.state}] {self.app_identifier} ({self.duration_seconds:.1f}s)"


class DailyMetrics(TenantModel):
    """Aggregated daily metrics per device adhering to §7.2 and §9.2.
    
    Unique grain: (device_id, local_date, calc_version) (REQ-9-5).
    """

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="daily_metrics",
        db_index=True,
    )
    local_date = models.DateField(db_index=True)
    calc_version = models.IntegerField(default=1, db_index=True)

    observed_session_seconds = models.FloatField(
        default=0.0,
        help_text="Sum of intervals where agent was running and not in gap state (§9.2).",
    )
    active_seconds = models.FloatField(
        default=0.0,
        help_text="Time in foreground app with no idle (§9.2).",
    )
    idle_seconds = models.FloatField(
        default=0.0,
        help_text="Time where idle threshold was exceeded (§9.2).",
    )
    productive_seconds = models.FloatField(default=0.0)
    neutral_seconds = models.FloatField(default=0.0)
    distracting_seconds = models.FloatField(default=0.0)
    productive_share = models.FloatField(
        default=0.0,
        help_text="productive / (productive + neutral + distracting). Preserves denominator.",
    )
    monitoring_coverage = models.FloatField(
        default=0.0,
        help_text="observed session / scheduled work hours (§9.2).",
    )
    sync_lag_seconds = models.FloatField(
        default=0.0,
        help_text="Age of oldest unsynced event (§9.2).",
    )
    crash_free_sessions = models.IntegerField(default=0)
    data_freshness_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp of most recent event contributing to this aggregate (§9.3, E74).",
    )

    class Meta:
        db_table = "daily_metrics"
        ordering = ["-local_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "local_date", "calc_version"],
                name="unique_daily_metrics_grain",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "local_date"]),
            models.Index(fields=["device", "local_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.device} on {self.local_date} (v{self.calc_version}): {self.active_seconds:.0f}s active"


class DataExport(TenantModel):
    """Tracks background report export jobs (§8.4, E81, E82)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="data_exports",
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=ExportStatus.choices,
        default=ExportStatus.PENDING,
        db_index=True,
    )
    export_type = models.CharField(
        max_length=32,
        choices=ExportType.choices,
        default=ExportType.DAILY_METRICS,
        db_index=True,
    )
    filters = models.JSONField(default=dict, blank=True)
    file_key = models.CharField(max_length=512, blank=True, default="")
    download_url = models.TextField(blank=True, default="")
    row_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "data_exports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["user", "created_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at
