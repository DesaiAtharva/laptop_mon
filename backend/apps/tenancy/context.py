"""Tenant context resolution logic for middleware and DRF authenticators."""
from __future__ import annotations

import uuid
from typing import Any
from django.http import HttpRequest
from rest_framework.exceptions import NotFound, ValidationError
from apps.common.exceptions import TenantDeleted, TenantSuspended
from apps.tenancy.models import Membership, MembershipStatus, TenantStatus

EXEMPT_PREFIXES = (
    "/api/auth/",
    "/api/me/tenants",
    "/api/support-access/request",
    "/static/",
)


def resolve_tenant_context(request: HttpRequest, user: Any) -> tuple[Any, Any]:
    """Resolves and validates the active tenant and membership for the request.

    Enforces:
    - Multi-tenant explicit X-Tenant-ID header requirement (E46)
    - Cross-tenant IDOR protection (E45)
    - Suspended (E43) and Deleting (E44) tenant status checks
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None, None

    # Already resolved
    if getattr(request, "tenant", None) and getattr(request, "membership", None):
        return request.tenant, request.membership

    path = request.path_info or request.path

    # Exempt routes
    for prefix in EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None, None

    # Exclude organization creation
    if path == "/api/tenants" and request.method == "POST":
        return None, None

    tenant_header = request.headers.get("X-Tenant-ID")

    active_memberships = Membership.objects.filter(
        user=user,
        status=MembershipStatus.ACTIVE,
    ).select_related("tenant")

    if tenant_header:
        try:
            target_tenant_id = uuid.UUID(tenant_header)
        except (ValueError, TypeError):
            raise ValidationError({"X-Tenant-ID": ["Invalid UUID format."]})

        membership = active_memberships.filter(tenant_id=target_tenant_id).first()
        if not membership:
            raise NotFound("Tenant not found or access denied.")
    else:
        count = active_memberships.count()
        if count == 1:
            membership = active_memberships.first()
        elif count > 1:
            raise ValidationError(
                {"code": "tenant_context_required", "message": "User belongs to multiple organizations. Please provide an explicit X-Tenant-ID header."}
            )
        else:
            membership = None

    if membership:
        tenant = membership.tenant
        if tenant.status == TenantStatus.SUSPENDED:
            raise TenantSuspended("Tenant organization is currently suspended.")
        if tenant.status == TenantStatus.DELETING:
            raise TenantDeleted("Tenant organization not found or is being deleted.")

        request.tenant = tenant  # type: ignore[attr-defined]
        request.membership = membership  # type: ignore[attr-defined]
        return tenant, membership

    return None, None
