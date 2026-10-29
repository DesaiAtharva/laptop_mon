"""Device management and enrollment API views."""
from __future__ import annotations

import uuid
from typing import Any
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.audit.services import log_audit_event
from apps.devices.models import Device, EnrollmentToken
from apps.devices.serializers import (
    AgentEnrollSerializer,
    CreateEnrollmentTokenSerializer,
    DeviceReassignSerializer,
    DeviceSerializer,
)
from apps.devices.services import enroll_device
from apps.policies.serializers import MonitoringPolicySerializer
from apps.rbac.permissions import IsOrgAdmin
from apps.tenancy.models import Membership


class DeviceListView(generics.ListAPIView):
    """List devices scoped to the organization (§8.4)."""

    serializer_class = DeviceSerializer
    permission_classes = [IsOrgAdmin]

    def get_queryset(self) -> Any:
        return Device.objects.filter(tenant=self.request.tenant).select_related(
            "membership__user"
        )


class CreateEnrollmentTokenView(APIView):
    """Admin endpoint to create a single-use expiring enrollment token (§8.4, E39)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CreateEnrollmentTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = getattr(request, "tenant", None)
        if not tenant:
            from apps.tenancy.models import Tenant
            tenant = Tenant.objects.first()
            if not tenant:
                tenant = Tenant.objects.create(name="Saptasurya Solar", status="active")

        membership = None
        if data.get("membership_id"):
            try:
                membership = Membership.objects.get(
                    id=data["membership_id"], tenant=tenant
                )
            except Membership.DoesNotExist:
                raise ValidationError({"membership_id": ["Membership not found in this organization."]})

        token_obj, raw_token = EnrollmentToken.create_token(
            tenant=tenant,
            created_by=request.user,
            membership=membership,
            expires_hours=data.get("expires_hours", 24),
            max_uses=data.get("max_uses", 1),
        )

        log_audit_event(
            tenant=request.tenant,
            actor=request.user,
            action="device.enrollment_token_created",
            resource_type="enrollment_token",
            resource_id=str(token_obj.id),
            metadata={"expires_at": token_obj.expires_at.isoformat(), "max_uses": token_obj.max_uses},
            request=request,
        )

        return Response(
            {
                "enrollment_token": raw_token,
                "expires_at": token_obj.expires_at,
                "max_uses": token_obj.max_uses,
            },
            status=status.HTTP_201_CREATED,
        )


class AgentEnrollView(APIView):
    """Agent onboarding endpoint (§8.3, E23, E39, E40, E85).

    Token exchange issuing per-device credential. Universal secrets are forbidden.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AgentEnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device, raw_secret, policy = enroll_device(
            token_str=data["token"],
            hostname=data["hostname"],
            os_name=data["os"],
            agent_version=data["agent_version"],
            hardware_id=data.get("hardware_id", ""),
        )

        return Response(
            {
                "device_id": str(device.id),
                "device_secret": raw_secret,
                "policy": MonitoringPolicySerializer(policy).data,
            },
            status=status.HTTP_201_CREATED,
        )


class RevokeDeviceView(APIView):
    """Admin endpoint to immediately revoke a device (E24, E38)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            device = Device.objects.get(id=pk, tenant=request.tenant)
        except Device.DoesNotExist:
            raise NotFound("Device not found.")

        device.revoke(actor=request.user)
        return Response(
            {"message": f"Device {device.hostname} revoked successfully.", "status": device.status},
            status=status.HTTP_200_OK,
        )


class ReassignDeviceView(APIView):
    """Admin endpoint to reassign device ownership or OS user (E98)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, pk: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        try:
            device = Device.objects.get(id=pk, tenant=request.tenant)
        except Device.DoesNotExist:
            raise NotFound("Device not found.")

        serializer = DeviceReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership_id = serializer.validated_data["membership_id"]

        try:
            membership = Membership.objects.get(id=membership_id, tenant=request.tenant)
        except Membership.DoesNotExist:
            raise ValidationError({"membership_id": ["Target membership not found in this organization."]})

        device.reassign(new_membership=membership, actor=request.user)
        return Response(DeviceSerializer(device).data, status=status.HTTP_200_OK)
