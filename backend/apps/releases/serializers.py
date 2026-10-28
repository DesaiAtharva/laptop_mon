"""
backend/apps/releases/serializers.py — Serializers for Release Manifests and Admin Management.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.releases.models import AgentRelease


class ReleaseManifestSerializer(serializers.ModelSerializer):
    """
    Public manifest format returned to updating agents.
    """

    sha256 = serializers.CharField(source="sha256_checksum")

    class Meta:
        model = AgentRelease
        fields = [
            "version",
            "channel",
            "platform",
            "package_url",
            "sha256",
            "signature",
            "min_agent_version",
            "max_agent_version",
            "release_notes",
        ]


class AdminReleaseSerializer(serializers.ModelSerializer):
    """
    Serializer for admin release publication and staged rollout management.
    """

    class Meta:
        model = AgentRelease
        fields = [
            "id",
            "version",
            "channel",
            "platform",
            "package_url",
            "sha256_checksum",
            "signature",
            "rollout_percentage",
            "min_agent_version",
            "max_agent_version",
            "is_active",
            "release_notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
