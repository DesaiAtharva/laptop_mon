"""Serializers for screenshot upload, completion, viewing, and legal workflows."""
from __future__ import annotations

from rest_framework import serializers
from apps.screenshots.models import Screenshot


class ScreenshotUploadIntentRequestSerializer(serializers.Serializer):
    """Payload for POST /api/agent/screenshots/upload-intents (§6.2, §8.3)."""

    screenshot_id = serializers.UUIDField(required=True)
    captured_at = serializers.DateTimeField(required=True)
    policy_version = serializers.IntegerField(default=1, min_value=1)
    content_type = serializers.CharField(required=True, max_length=64)
    file_size = serializers.IntegerField(required=True, min_value=1)


class ScreenshotCompleteRequestSerializer(serializers.Serializer):
    """Payload for POST /api/agent/screenshots/complete (§6.2, §8.3)."""

    screenshot_id = serializers.UUIDField(required=True)
    checksum = serializers.CharField(required=True, max_length=128)
    file_size = serializers.IntegerField(required=True, min_value=1)
    width = serializers.IntegerField(required=False, default=None)
    height = serializers.IntegerField(required=False, default=None)


class ScreenshotMetadataSerializer(serializers.ModelSerializer):
    """Serialized metadata for dashboard screenshot gallery (§8.4, §10.2)."""

    device_id = serializers.UUIDField(source="device.id", read_only=True)
    device_hostname = serializers.CharField(source="device.hostname", read_only=True)

    class Meta:
        model = Screenshot
        fields = [
            "id",
            "device_id",
            "device_hostname",
            "status",
            "captured_at",
            "width",
            "height",
            "file_size",
            "policy_version",
            "delete_after",
            "legal_hold",
            "created_at",
        ]
        read_only_fields = fields


class LegalHoldRequestSerializer(serializers.Serializer):
    """Payload for applying legal hold (§11.2, E90)."""

    reason = serializers.CharField(required=True, min_length=5)
    screenshot_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    device_id = serializers.UUIDField(required=False, default=None)


class LegalDeleteRequestSerializer(serializers.Serializer):
    """Payload for legal deletion request (§11.2, E90)."""

    reason = serializers.CharField(required=True, min_length=5)
    screenshot_ids = serializers.ListField(
        child=serializers.UUIDField(), required=True, min_length=1
    )


class RetroactiveExclusionRequestSerializer(serializers.Serializer):
    """Payload for retroactive exclusion handling (E55)."""

    app_identifier = serializers.CharField(required=True)
    action = serializers.ChoiceField(choices=["keep", "purge", "flag_legal_review"])
    policy_version = serializers.IntegerField(required=True, min_value=1)
