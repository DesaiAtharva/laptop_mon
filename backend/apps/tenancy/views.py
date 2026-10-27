"""Tenancy API views implementing §8.2 auth/tenant endpoints and lifecycle changes."""
from __future__ import annotations

import uuid
from typing import Any
from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.audit.services import log_audit_event
from apps.common.exceptions import ApplicationConflict
from apps.rbac.permissions import IsOrgAdmin, IsTenantMember
from apps.tenancy.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    Tenant,
    TenantStatus,
)
from apps.tenancy.serializers import (
    InvitationCreateSerializer,
    InvitationSerializer,
    MembershipSerializer,
    MembershipUpdateSerializer,
    TenantSerializer,
)
from apps.tenancy.services import change_membership_role, change_membership_team


class MeTenantsView(APIView):
    """List all organizations in which the authenticated user has an active membership (§8.2)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        memberships = (
            Membership.objects.filter(
                user=request.user,
                status=MembershipStatus.ACTIVE,
                tenant__status__in=[TenantStatus.ACTIVE, TenantStatus.SUSPENDED],
            )
            .select_related("tenant")
            .order_by("-created_at")
        )

        results = []
        for m in memberships:
            results.append(
                {
                    "tenant_id": str(m.tenant.id),
                    "name": m.tenant.name,
                    "status": m.tenant.status,
                    "role": m.role,
                    "has_screenshot_permission": m.has_screenshot_permission,
                }
            )

        return Response({"tenants": results}, status=status.HTTP_200_OK)


class CreateTenantView(APIView):
    """Create a new tenant organization (§8.2).

    The authenticated creator is automatically provisioned as Organization Admin.
    """

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        name = request.data.get("name", "").strip()
        if not name:
            raise ValidationError({"name": ["Organization name cannot be blank."]})

        tenant = Tenant.objects.create(name=name, status=TenantStatus.ACTIVE)

        membership = Membership.objects.create(
            tenant=tenant,
            user=request.user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        log_audit_event(
            tenant=tenant,
            actor=request.user,
            action="tenant.created",
            resource_type="tenant",
            resource_id=str(tenant.id),
            metadata={"name": tenant.name},
            request=request,
        )

        return Response(
            {
                "tenant": TenantSerializer(tenant).data,
                "membership": MembershipSerializer(membership).data,
            },
            status=status.HTTP_201_CREATED,
        )


class TenantMembersListView(APIView):
    """List members of a tenant organization (§8.2).

    Accessible by Organization Admins only.
    Guarantees cross-tenant isolation (E45).
    """

    permission_classes = [IsOrgAdmin]

    def get(self, request: Request, tenant_id: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        # Cross-tenant IDOR protection (E45):
        if request.tenant.id != tenant_id:
            raise NotFound("Tenant not found.")

        members = (
            Membership.objects.filter(tenant=request.tenant)
            .select_related("user")
            .prefetch_related("team_memberships__team")
            .order_by("user__name", "user__email")
        )
        serializer = MembershipSerializer(members, many=True)
        return Response({"members": serializer.data}, status=status.HTTP_200_OK)


class TenantInvitationsView(APIView):
    """Invite a user to the organization (§8.2).

    Prevents duplicate pending invitations and account enumeration.
    """

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request, tenant_id: uuid.UUID, *args: Any, **kwargs: Any) -> Response:
        # Cross-tenant IDOR protection (E45)
        if request.tenant.id != tenant_id:
            raise NotFound("Tenant not found.")

        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()
        role = serializer.validated_data["role"]

        # Prevent duplicate pending invitations
        if Invitation.objects.filter(
            tenant=request.tenant,
            email=email,
            status=InvitationStatus.PENDING,
        ).exists():
            raise ApplicationConflict("An active pending invitation already exists for this email address.")

        # Check if already active member
        if Membership.objects.filter(
            tenant=request.tenant,
            user__email=email,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise ApplicationConflict("User is already an active member of this organization.")

        invitation, raw_token = Invitation.create_invitation(
            tenant=request.tenant,
            email=email,
            role=role,
        )

        log_audit_event(
            tenant=request.tenant,
            actor=request.user,
            action="invitation.created",
            resource_type="invitation",
            resource_id=str(invitation.id),
            metadata={"email": email, "role": role},
            request=request,
        )

        return Response(
            {
                "invitation": InvitationSerializer(invitation).data,
                "invitation_token": raw_token,
            },
            status=status.HTTP_201_CREATED,
        )


class TenantMemberDetailView(APIView):
    """Update membership role, team assignment, or active status (E41, E42, E47)."""

    permission_classes = [IsOrgAdmin]

    def patch(
        self,
        request: Request,
        tenant_id: uuid.UUID,
        member_id: uuid.UUID,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        # Cross-tenant protection (E45)
        if request.tenant.id != tenant_id:
            raise NotFound("Tenant not found.")

        try:
            membership = Membership.objects.select_related("user").get(
                id=member_id,
                tenant=request.tenant,
            )
        except Membership.DoesNotExist:
            raise NotFound("Member not found.")

        serializer = MembershipUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "role" in data and data["role"] != membership.role:
            change_membership_role(membership, data["role"], actor=request.user)

        if "team_id" in data:
            team_id = data["team_id"]
            new_team = None
            if team_id is not None:
                try:
                    new_team = Team.objects.get(id=team_id, tenant=request.tenant)
                except Team.DoesNotExist:
                    raise ValidationError({"team_id": ["Target team not found in this organization."]})
            change_membership_team(membership, new_team, actor=request.user)

        if "has_screenshot_permission" in data:
            membership.has_screenshot_permission = data["has_screenshot_permission"]
            membership.save(update_fields=["has_screenshot_permission", "updated_at"])

        if "status" in data and data["status"] != membership.status:
            if data["status"] == MembershipStatus.DISABLED:
                membership.disable()  # E42 hook
            else:
                membership.status = data["status"]
                membership.save(update_fields=["status", "updated_at"])

        membership.refresh_from_db()
        return Response(MembershipSerializer(membership).data, status=status.HTTP_200_OK)
