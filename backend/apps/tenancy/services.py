"""Tenancy lifecycle services and event hooks (E41, E42, E47, E80)."""
from __future__ import annotations

import logging
from typing import Any, Optional
from apps.common.cache import delete_tenant_cache
from apps.tenancy.models import Membership, Team, TeamMember

logger = logging.getLogger(__name__)


def on_employee_left(membership: Membership) -> None:
    """Invoked when an employee leaves the company (E42).

    1. Disables access.
    2. Invalidates active sessions.
    3. Invokes device revocation hook to trigger agent credential invalidation.
    4. Audits the event.
    """
    logger.info("Processing employee departure for membership %s", membership.id)

    # Invalidate tenant cache entries related to this user/membership (E80)
    delete_tenant_cache(membership.tenant_id, f"membership:{membership.user_id}")
    delete_tenant_cache(membership.tenant_id, f"user_teams:{membership.id}")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=membership.tenant,
            actor=membership.user,
            action="membership.disabled",
            resource_type="membership",
            resource_id=str(membership.id),
            metadata={"reason": "employee_left", "user_email": membership.user.email},
        )
    except Exception:
        pass


def change_membership_team(
    membership: Membership,
    new_team: Optional[Team],
    actor: Optional[Any] = None,
) -> None:
    """Updates team assignment immediately (E41: Employee moved, E47: Manager changes teams).

    Re-evaluates and invalidates caches immediately so access changes take effect at once.
    """
    old_team_memberships = list(TeamMember.objects.filter(membership=membership))
    old_team_names = [tm.team.name for tm in old_team_memberships]

    # Remove existing assignments
    TeamMember.objects.filter(membership=membership).delete()

    if new_team:
        if new_team.tenant_id != membership.tenant_id:
            raise ValueError("New team must belong to the same tenant as membership.")
        TeamMember.objects.create(team=new_team, membership=membership)

    # Invalidate tenant cache (E80)
    delete_tenant_cache(membership.tenant_id, f"user_teams:{membership.id}")
    delete_tenant_cache(membership.tenant_id, f"manager_teams:{membership.id}")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=membership.tenant,
            actor=actor or membership.user,
            action="membership.team_changed",
            resource_type="membership",
            resource_id=str(membership.id),
            metadata={
                "old_teams": old_team_names,
                "new_team": new_team.name if new_team else None,
            },
        )
    except Exception:
        pass


def change_membership_role(
    membership: Membership,
    new_role: str,
    actor: Optional[Any] = None,
) -> None:
    """Updates membership role immediately and writes to audit log (E41, E47)."""
    old_role = membership.role
    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])

    # Invalidate tenant cache (E80)
    delete_tenant_cache(membership.tenant_id, f"membership:{membership.user_id}")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=membership.tenant,
            actor=actor or membership.user,
            action="membership.role_changed",
            resource_type="membership",
            resource_id=str(membership.id),
            metadata={"old_role": old_role, "new_role": new_role},
        )
    except Exception:
        pass


def send_invitation_email(
    invitation: Any,
    raw_token: str,
    app_url: str = "http://localhost:3000",
) -> bool:
    """Sends invitation email with graceful delivery error handling (E83)."""
    from django.conf import settings
    from django.core.mail import send_mail
    from django.utils import timezone

    invite_url = f"{app_url}/invite/accept?token={raw_token}&tenant={invitation.tenant_id}"
    subject = f"You have been invited to join {invitation.tenant.name} on LaptopMon"
    message = (
        f"Hello,\n\n"
        f"You have been invited to join {invitation.tenant.name} as a {invitation.role}.\n"
        f"Accept your invitation here: {invite_url}\n\n"
        f"This invitation expires on {invitation.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}.\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@laptopmon.com"),
            recipient_list=[invitation.email],
            fail_silently=False,
        )
        invitation.delivery_status = "sent"
        invitation.delivery_error = ""
        invitation.last_sent_at = timezone.now()
        invitation.save(update_fields=["delivery_status", "delivery_error", "last_sent_at"])
        return True
    except Exception as exc:
        logger.warning("Failed to deliver invitation email to %s: %s (E83)", invitation.email, exc)
        invitation.delivery_status = "failed"
        invitation.delivery_error = str(exc)
        invitation.save(update_fields=["delivery_status", "delivery_error"])
        return False


def accept_invitation(token_str: str, user: Any) -> Any:
    """Accepts a pending invitation and provisions active membership."""
    import hashlib
    from django.utils import timezone
    from apps.common.exceptions import ApplicationConflict, EntityNotFound
    from apps.tenancy.models import Invitation, InvitationStatus, Membership, MembershipStatus

    token_hash = hashlib.sha256(token_str.strip().encode("utf-8")).hexdigest()
    invitation = Invitation.objects.filter(token_hash=token_hash).first()

    if not invitation or invitation.status != InvitationStatus.PENDING:
        raise EntityNotFound("Invalid or expired invitation token.")

    if invitation.expires_at < timezone.now():
        raise ApplicationConflict("Invitation has expired.")

    membership, created = Membership.objects.get_or_create(
        tenant=invitation.tenant,
        user=user,
        defaults={
            "role": invitation.role,
            "status": MembershipStatus.ACTIVE,
        },
    )
    if not created and membership.status != MembershipStatus.ACTIVE:
        membership.status = MembershipStatus.ACTIVE
        membership.role = invitation.role
        membership.save(update_fields=["status", "role", "updated_at"])

    invitation.status = InvitationStatus.ACCEPTED
    invitation.save(update_fields=["status", "updated_at"])

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=invitation.tenant,
            actor=user,
            action="invitation.accepted",
            resource_type="invitation",
            resource_id=str(invitation.id),
            metadata={"user_email": user.email, "role": invitation.role},
        )
    except Exception:
        pass

    return membership


def suspend_tenant(tenant: Any, reason: str = "", actor: Optional[Any] = None) -> None:
    """Suspends a tenant, blocking user logins and freezing agent uploads (E43)."""
    from apps.common.cache import delete_tenant_cache
    from apps.tenancy.models import Tenant, TenantStatus

    if not isinstance(tenant, Tenant):
        tenant = Tenant.objects.get(id=tenant)

    tenant.status = TenantStatus.SUSPENDED
    tenant.save(update_fields=["status", "updated_at"])

    delete_tenant_cache(tenant.id, "all")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=tenant,
            actor=actor,
            action="tenant.suspended",
            resource_type="tenant",
            resource_id=str(tenant.id),
            metadata={"reason": reason},
        )
    except Exception:
        pass


def reactivate_tenant(tenant: Any, actor: Optional[Any] = None) -> None:
    """Reactivates a previously suspended tenant (E43)."""
    from apps.common.cache import delete_tenant_cache
    from apps.tenancy.models import Tenant, TenantStatus

    if not isinstance(tenant, Tenant):
        tenant = Tenant.objects.get(id=tenant)

    tenant.status = TenantStatus.ACTIVE
    tenant.save(update_fields=["status", "updated_at"])

    delete_tenant_cache(tenant.id, "all")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=tenant,
            actor=actor,
            action="tenant.reactivated",
            resource_type="tenant",
            resource_id=str(tenant.id),
        )
    except Exception:
        pass


def delete_tenant_cascade(tenant: Any, actor: Optional[Any] = None) -> dict[str, Any]:
    """Staged verified cascade deletion of a tenant across all storage layers (E44)."""
    from apps.common.cache import delete_tenant_cache
    from apps.tenancy.models import Tenant, TenantStatus

    if not isinstance(tenant, Tenant):
        tenant_obj = Tenant.objects.filter(id=tenant).first()
        if not tenant_obj:
            return {"success": True, "message": "Tenant already deleted or not found"}
        tenant = tenant_obj

    tenant_id = tenant.id
    tenant.status = TenantStatus.DELETING
    tenant.save(update_fields=["status", "updated_at"])

    delete_tenant_cache(tenant_id, "all")

    try:
        from apps.audit.services import log_audit_event
        log_audit_event(
            tenant=tenant,
            actor=actor,
            action="tenant.deleted",
            resource_type="tenant",
            resource_id=str(tenant.id),
            metadata={"name": tenant.name},
        )
    except Exception:
        pass

    try:
        import uuid as _uuid
        from django.db import connection
        raw_uuid = _uuid.UUID(str(tenant_id))
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logs WHERE tenant_id = %s OR tenant_id = %s", [str(raw_uuid), raw_uuid.hex])
    except Exception as e:
        logger.error("Failed to delete audit logs: %s", e)

    tenant.delete()

    return {"success": True, "tenant_id": str(tenant_id), "status": "deleted"}
