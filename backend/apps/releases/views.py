"""
backend/apps/releases/views.py — Release Distribution and Rollout Management Views.

Adheres to:
- Spec §4.1: Signed release manifest with staged rollout percentage bucketing.
- Audited release creation for Org Admins (E91, REQ-4-5).
- Machine-readable responses for agents.
- Version compatibility filtering (E16).
"""

from __future__ import annotations

import hashlib
from typing import Tuple
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_audit_event
from apps.rbac.permissions import IsOrgAdmin
from apps.releases.models import AgentRelease
from apps.releases.serializers import AdminReleaseSerializer, ReleaseManifestSerializer


def _parse_version(v_str: str) -> Tuple[int, ...]:
    """Parse version string into tuple of ints for semantic comparison."""
    parts = []
    for x in v_str.replace("-", ".").split("."):
        if x.isdigit():
            parts.append(int(x))
    return tuple(parts) if parts else (0,)


class AgentReleaseLatestView(APIView):
    """
    Public or device-authenticated endpoint for agents checking for updates.
    GET /api/agent/releases/latest/
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        platform_name = request.query_params.get("platform", "windows").lower()
        channel = request.query_params.get("channel", "stable").lower()
        current_version = request.query_params.get("current_version", "1.0.0")
        device_id = request.headers.get("X-Device-Id") or request.query_params.get("device_id", "")

        # Find latest active release for this platform & channel
        releases = AgentRelease.objects.filter(
            platform=platform_name,
            channel=channel,
            is_active=True,
        ).order_by("-created_at")

        if not releases.exists():
            return Response({"update_available": False, "message": "No active releases found"}, status=status.HTTP_200_OK)

        candidate = releases.first()
        assert candidate is not None

        # If already running candidate version
        if candidate.version == current_version:
            return Response(
                {"update_available": False, "message": "Already up to date", "version": current_version},
                status=status.HTTP_200_OK,
            )

        # Version compatibility verification (E16)
        cur_v = _parse_version(current_version)
        if candidate.min_agent_version:
            min_v = _parse_version(candidate.min_agent_version)
            if cur_v < min_v:
                return Response(
                    {"update_available": False, "message": "Current version below min_agent_version", "version": candidate.version},
                    status=status.HTTP_200_OK,
                )

        if candidate.max_agent_version:
            max_v = _parse_version(candidate.max_agent_version)
            if cur_v > max_v:
                return Response(
                    {"update_available": False, "message": "Current version exceeds max_agent_version", "version": candidate.version},
                    status=status.HTTP_200_OK,
                )

        # Check rollout percentage bucketing (hash device ID to 0-99)
        if candidate.rollout_percentage < 100:
            seed = f"{device_id}:{candidate.version}"
            bucket = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % 100
            if bucket >= candidate.rollout_percentage:
                return Response(
                    {"update_available": False, "message": "Not yet enrolled in staged rollout bucket"},
                    status=status.HTTP_200_OK,
                )

        serializer = ReleaseManifestSerializer(candidate)
        data = dict(serializer.data)
        data["update_available"] = True
        return Response(data, status=status.HTTP_200_OK)


class AdminReleaseListCreateView(generics.ListCreateAPIView):
    """
    Admin endpoint to view and publish releases.
    GET /api/releases/
    POST /api/releases/
    """

    permission_classes = [IsOrgAdmin]
    queryset = AgentRelease.objects.all().order_by("-created_at")
    serializer_class = AdminReleaseSerializer

    def perform_create(self, serializer: AdminReleaseSerializer) -> None:
        release = serializer.save()
        user = self.request.user
        tenant = getattr(self.request, "tenant", None)
        log_audit_event(
            action="agent.release.created",
            resource_type="agent_release",
            resource_id=str(release.id),
            actor=user if user.is_authenticated else None,
            tenant=tenant,
            metadata={
                "version": release.version,
                "platform": release.platform,
                "channel": release.channel,
                "rollout_percentage": release.rollout_percentage,
            },
            request=self.request,
        )
