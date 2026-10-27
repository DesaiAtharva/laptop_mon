"""Audit service for recording immutable audit events (§11.1)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from django.http import HttpRequest
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.common.middleware import get_current_correlation_id
from apps.tenancy.models import Tenant

logger = logging.getLogger(__name__)


def log_audit_event(
    action: str,
    resource_type: str,
    resource_id: str,
    actor: Optional[User] = None,
    tenant: Optional[Tenant] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request: Optional[HttpRequest] = None,
    request_id: Optional[str] = None,
) -> AuditLog:
    """Record an immutable audit log entry (§11.1).

    Actions that must be logged include:
    - Sign-in, sign-out, MFA events
    - Member invite, role change, disable
    - Team creation, membership change
    - Support access request, approval, use
    - Policy updates and exports
    """
    if request:
        if not actor and getattr(request, "user", None) and request.user.is_authenticated:
            actor = request.user
        if not tenant and getattr(request, "tenant", None):
            tenant = request.tenant
        if not request_id:
            request_id = getattr(request, "correlation_id", None) or get_current_correlation_id()

    if not request_id:
        request_id = get_current_correlation_id()

    entry = AuditLog.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        metadata=metadata or {},
        request_id=request_id,
    )
    logger.info(
        "AUDIT [%s] %s on %s:%s by actor=%s (request_id=%s)",
        tenant.id if tenant else "platform",
        action,
        resource_type,
        resource_id,
        actor.id if actor else "anonymous",
        request_id,
    )
    return entry
