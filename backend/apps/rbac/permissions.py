"""RBAC permission classes and scoping helpers strictly adhering to §2.2."""
from __future__ import annotations

from typing import Any, List
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, TeamMember


class IsTenantMember(permissions.BasePermission):
    """Requires request to have an active membership in the resolved tenant."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        membership: Membership | None = getattr(request, "membership", None)
        return membership is not None and membership.status == MembershipStatus.ACTIVE


class IsOrgAdmin(IsTenantMember):
    """Requires Organization Admin role or Platform Superuser (§2.1)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        membership: Membership = getattr(request, "membership")
        return membership.role == MembershipRole.ADMIN


class IsManager(IsTenantMember):
    """Requires Manager or Org Admin role (§2.1)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        membership: Membership = getattr(request, "membership")
        return membership.role in [MembershipRole.MANAGER, MembershipRole.ADMIN]


class IsAuditor(IsTenantMember):
    """Requires Auditor or Org Admin role (§2.1)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        membership: Membership = getattr(request, "membership")
        return membership.role in [MembershipRole.AUDITOR, MembershipRole.ADMIN]


class HasScreenshotPermission(IsTenantMember):
    """Requires explicit screenshot permission (§2.2).

    Screenshot access is a separate, explicit permission flag on the membership.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        membership: Membership = getattr(request, "membership")
        return bool(membership.has_screenshot_permission or request.user.is_superuser)


def get_manager_accessible_team_ids(membership: Membership) -> List[Any]:
    """Returns list of team IDs that this manager is assigned to (§2.2, E41, E47).

    - Org Admins see all teams in the tenant.
    - Managers see ONLY their assigned teams.
    - Employees see only their assigned teams.
    """
    if membership.role == MembershipRole.ADMIN or membership.user.is_superuser:
        return list(membership.tenant.teams.values_list("id", flat=True))

    return list(
        TeamMember.objects.filter(membership=membership).values_list("team_id", flat=True)
    )
