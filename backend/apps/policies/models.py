"""MonitoringPolicy and AppRule models adhering to §7.2, E37, and E99."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict
from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from apps.common.exceptions import ApplicationConflict
from apps.tenancy.models import Tenant, TenantModel


class AppClassification(models.TextChoices):
    PRODUCTIVE = "productive", "Productive"
    NEUTRAL = "neutral", "Neutral"
    DISTRACTING = "distracting", "Distracting"
    EXCLUDED = "excluded", "Excluded"


class MonitoringPolicy(TenantModel):
    """Organization monitoring policy with optimistic locking and offline grace (§7.2, E37, E99)."""

    version = models.IntegerField(default=1, db_index=True)
    valid_until = models.DateTimeField(
        help_text="Grace timestamp beyond which offline agents must not capture data (E37)."
    )
    screenshot_interval_seconds = models.IntegerField(default=300)
    idle_threshold_seconds = models.IntegerField(default=180)
    retention_days = models.IntegerField(default=30)
    capture_windows = models.JSONField(default=dict, blank=True)
    exclusion_rules = models.JSONField(default=dict, blank=True)
    window_title_collection = models.BooleanField(default=True)
    min_agent_version = models.CharField(max_length=32, default="1.0.0")
    max_agent_version = models.CharField(max_length=32, default="99.9.9")
    effective_date = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "monitoring_policies"
        ordering = ["-version"]
        indexes = [
            models.Index(fields=["tenant", "version"]),
        ]

    def __str__(self) -> str:
        return f"Policy v{self.version} for {self.tenant.name}"

    @property
    def signature(self) -> str:
        """Deterministic policy digest sent to agents for tamper verification."""
        canonical = json.dumps(
            {
                "version": self.version,
                "screenshot_interval_seconds": self.screenshot_interval_seconds,
                "idle_threshold_seconds": self.idle_threshold_seconds,
                "window_title_collection": self.window_title_collection,
                "min_agent_version": self.min_agent_version,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def get_or_create_default(cls, tenant: Tenant) -> MonitoringPolicy:
        """Get the latest effective policy or provision default v1."""
        policy = cls.objects.filter(tenant=tenant).order_by("-version").first()
        if not policy:
            now = timezone.now()
            policy = cls.objects.create(
                tenant=tenant,
                version=1,
                valid_until=now + timezone.timedelta(days=30),  # 30-day offline grace (E37)
                screenshot_interval_seconds=300,
                idle_threshold_seconds=180,
                retention_days=30,
                capture_windows={
                    "work_hours": {"start": "09:00", "end": "18:00"},
                    "weekdays": [1, 2, 3, 4, 5],
                },
                exclusion_rules={"private_apps": ["1Password", "KeePass", "Bitwarden"]},
                window_title_collection=True,
                min_agent_version="1.0.0",
                max_agent_version="99.9.9",
                effective_date=now,
            )
        return policy

    def update_with_optimistic_lock(self, expected_version: int, **fields: Any) -> None:
        """Updates policy using optimistic concurrency control (E99).

        Raises ApplicationConflict if version mismatch is detected.
        """
        if self.version != expected_version:
            from apps.audit.services import log_audit_event
            log_audit_event(
                tenant=self.tenant,
                action="policy.concurrent_edit_conflict",
                resource_type="policy",
                resource_id=str(self.id),
                metadata={
                    "current_version": self.version,
                    "attempted_version": expected_version,
                },
            )
            raise ApplicationConflict(
                "Concurrent policy modification detected. Policy has been updated by another administrator. Please reload.",
                code="version_conflict",
            )

        for k, v in fields.items():
            setattr(self, k, v)
        self.version += 1
        self.save()


class AppRule(TenantModel):
    """Productivity categorization rules for foreground applications (§7.2)."""

    policy = models.ForeignKey(
        MonitoringPolicy,
        on_delete=models.CASCADE,
        related_name="app_rules",
        db_index=True,
    )
    app_identifier = models.CharField(max_length=255, db_index=True)
    classification = models.CharField(
        max_length=32,
        choices=AppClassification.choices,
        default=AppClassification.NEUTRAL,
    )
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "app_rules"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "policy", "app_identifier"],
                name="unique_tenant_policy_app",
            )
        ]
