"""Agent heartbeat and batch ingestion API views strictly per §8.3, §12.1."""
from __future__ import annotations

from typing import Any
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.devices.authentication import DeviceBearerAuthentication
from apps.ingestion.serializers import AgentHeartbeatSerializer, EventBatchUploadSerializer
from apps.ingestion.services import check_agent_version_compatibility, process_event_batch
from apps.policies.models import MonitoringPolicy


class AgentHeartbeatView(APIView):
    """Agent heartbeat endpoint (§8.3, §12.1, E16).

    Signals health, updates last seen, and enforces min/max agent version policies.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        device = getattr(request, "device", None)
        if not device:
            raise PermissionDenied("Device context missing.")

        serializer = AgentHeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        agent_version = data["agent_version"]
        policy = MonitoringPolicy.get_or_create_default(device.tenant)

        is_compatible, is_upgrade_required = check_agent_version_compatibility(agent_version, policy)

        now = timezone.now()
        device.last_seen_at = now
        device.agent_version = agent_version
        device.save(update_fields=["last_seen_at", "agent_version", "updated_at"])

        if is_upgrade_required:
            # E16: Minimum agent version enforced / Agent version deprecated
            return Response(
                {
                    "status": "upgrade_required",
                    "upgrade_required": True,
                    "min_agent_version": policy.min_agent_version,
                    "message": f"Agent version '{agent_version}' is deprecated. Minimum required version is '{policy.min_agent_version}'.",
                    "policy_version": policy.version,
                    "server_time": now,
                },
                status=status.HTTP_426_UPGRADE_REQUIRED,
            )

        return Response(
            {
                "status": "ok",
                "upgrade_required": False,
                "policy_version": policy.version,
                "server_time": now,
            },
            status=status.HTTP_200_OK,
        )


class AgentEventBatchIngestView(APIView):
    """High-throughput event batch ingestion endpoint (§6.1, §8.3, E02, E03, E25, E31–E36).

    Accepts durable telemetry events from agent local journal.
    Idempotent on retries. Commits durably before returning acknowledgment.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        device = getattr(request, "device", None)
        if not device:
            raise PermissionDenied("Device context missing.")

        serializer = EventBatchUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = process_event_batch(
            device=device,
            raw_events=data["events"],
            agent_version=data["agent_version"],
            schema_version=data.get("schema_version", 1),
        )

        # 207 Multi-Status if partial rejections, else 200 OK
        resp_status = status.HTTP_207_MULTI_STATUS if result["rejected"] else status.HTTP_200_OK
        return Response(result, status=resp_status)
