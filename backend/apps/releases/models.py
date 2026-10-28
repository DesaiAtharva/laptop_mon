"""
backend/apps/releases/models.py — Agent Release and Rollout Manifest Model.

Adheres to:
- Spec §4.1 (updater) and §15.1.
- Release channels (stable, beta), staged rollout percentages, min/max version enforcement.
- SHA-256 and cryptographic signature validation fields.
- MySQL InnoDB utf8mb4, UUID primary key, UTC timestamps.
"""

from __future__ import annotations

import uuid
from django.db import models


class ReleaseChannel(models.TextChoices):
    STABLE = "stable", "Stable"
    BETA = "beta", "Beta"
    NIGHTLY = "nightly", "Nightly"


class AgentRelease(models.Model):
    """
    Represents a signed desktop agent release package and distribution policy.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=32)
    channel = models.CharField(
        max_length=16,
        choices=ReleaseChannel.choices,
        default=ReleaseChannel.STABLE,
    )
    platform = models.CharField(max_length=16, default="windows")  # windows, macos, linux
    package_url = models.URLField(max_length=512)
    sha256_checksum = models.CharField(max_length=64)
    signature = models.TextField(help_text="Base64 encoded cryptographic signature of package")
    rollout_percentage = models.PositiveSmallIntegerField(
        default=100,
        help_text="Staged rollout percentage between 0 and 100",
    )
    min_agent_version = models.CharField(
        max_length=32,
        default="1.0.0",
        help_text="Minimum current agent version eligible to upgrade directly",
    )
    max_agent_version = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Maximum current agent version eligible to upgrade",
    )
    is_active = models.BooleanField(default=True)
    release_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_releases"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["platform", "channel", "is_active", "-created_at"]),
            models.Index(fields=["version"]),
        ]

    def __str__(self) -> str:
        return f"{self.platform}-{self.version} ({self.channel}) [{self.rollout_percentage}%]"
