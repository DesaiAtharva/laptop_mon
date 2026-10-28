"""Policy API views implementing §8.3 agent policy retrieval and §8.4 optimistic edits (E99)."""
from __future__ import annotations

import uuid
from typing import Any
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.audit.services import log_audit_event
from apps.devices.authentication import DeviceBearerAuthentication
from apps.policies.models import MonitoringPolicy
from apps.policies.serializers import MonitoringPolicySerializer, PolicyUpdateSerializer
from apps.rbac.permissions import IsOrgAdmin


class AgentPolicyView(APIView):
    """Effective monitoring policy endpoint for enrolled agents (§8.3).

    Requires DeviceBearer authentication.
    Returns versioned policy, expiration (valid_until for offline grace E37), and integrity signature.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        device = getattr(request, "device", None)
        if not device:
            raise PermissionDenied("Device context missing.")

        policy = MonitoringPolicy.get_or_create_default(device.tenant)
        serializer = MonitoringPolicySerializer(policy)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PolicyListView(APIView):
    """Organization policy view for administrators (§8.4)."""

    permission_classes = [IsOrgAdmin]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        policy = MonitoringPolicy.get_or_create_default(request.tenant)
        return Response(MonitoringPolicySerializer(policy).data, status=status.HTTP_200_OK)


class PolicyDetailUpdateView(APIView):
    """Update policy with optimistic concurrency control (E99)."""

    permission_classes = [IsOrgAdmin]

    def get(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            policy = MonitoringPolicy.objects.get(id=pk, tenant=request.tenant)
        except MonitoringPolicy.DoesNotExist:
            raise NotFound("Policy not found.")
        return Response(MonitoringPolicySerializer(policy).data, status=status.HTTP_200_OK)

    def patch(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            policy = MonitoringPolicy.objects.get(id=pk, tenant=request.tenant)
        except MonitoringPolicy.DoesNotExist:
            raise NotFound("Policy not found.")

        serializer = PolicyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        expected_version = data.pop("expected_version")
        policy.update_with_optimistic_lock(expected_version, **data)

        log_audit_event(
            tenant=request.tenant,
            actor=request.user,
            action="policy.updated",
            resource_type="policy",
            resource_id=str(policy.id),
            metadata={"new_version": policy.version, "updated_fields": list(data.keys())},
            request=request,
        )

        return Response(MonitoringPolicySerializer(policy).data, status=status.HTTP_200_OK)
