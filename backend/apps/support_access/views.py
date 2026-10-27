"""Support access API views enforcing E100 JIT workflow."""
from __future__ import annotations

from typing import Any
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.audit.services import log_audit_event
from apps.rbac.permissions import IsOrgAdmin
from apps.support_access.models import SupportAccessGrant, SupportAccessStatus
from apps.support_access.serializers import SupportAccessApproveSerializer, SupportAccessRequestSerializer


class RequestSupportAccessView(APIView):
    """Platform support user initiates a JIT access request (§2.1, E100)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SupportAccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        grant = serializer.save(requester=request.user)

        log_audit_event(
            tenant=grant.tenant,
            actor=request.user,
            action="support_access.requested",
            resource_type="support_grant",
            resource_id=str(grant.id),
            metadata={"reason": grant.reason},
            request=request,
        )

        return Response(
            SupportAccessRequestSerializer(grant).data,
            status=status.HTTP_201_CREATED,
        )


class ApproveSupportAccessView(APIView):
    """Organization Admin approves a JIT support access request (§2.1, E100)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        try:
            grant = SupportAccessGrant.objects.get(id=pk, tenant=request.tenant)
        except SupportAccessGrant.DoesNotExist:
            raise ValidationError("Support grant request not found.")

        if grant.status != SupportAccessStatus.PENDING:
            raise ValidationError(f"Grant cannot be approved in its current state ({grant.status}).")

        serializer = SupportAccessApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        duration = serializer.validated_data.get("duration_hours", 4)

        grant.approve(approver=request.user, duration_hours=duration)

        log_audit_event(
            tenant=grant.tenant,
            actor=request.user,
            action="support_access.approved",
            resource_type="support_grant",
            resource_id=str(grant.id),
            metadata={"duration_hours": duration, "expires_at": grant.expires_at.isoformat() if grant.expires_at else None},
            request=request,
        )

        return Response(
            SupportAccessRequestSerializer(grant).data,
            status=status.HTTP_200_OK,
        )


class RevokeSupportAccessView(APIView):
    """Organization Admin or Support Staff revokes an active support access grant (E100)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request, pk: str, *args: Any, **kwargs: Any) -> Response:
        try:
            grant = SupportAccessGrant.objects.get(id=pk)
        except SupportAccessGrant.DoesNotExist:
            raise ValidationError("Support grant not found.")

        # Allow either the assigned org admin or the requester themselves to revoke
        is_admin = getattr(request, "membership", None) and request.membership.role == "admin" and grant.tenant == request.tenant
        if not is_admin and grant.requester != request.user and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to revoke this grant.")

        grant.revoke()

        log_audit_event(
            tenant=grant.tenant,
            actor=request.user,
            action="support_access.revoked",
            resource_type="support_grant",
            resource_id=str(grant.id),
            metadata={"revoked_by": str(request.user.id)},
            request=request,
        )

        return Response(
            {"message": "Support access revoked successfully.", "status": grant.status},
            status=status.HTTP_200_OK,
        )
