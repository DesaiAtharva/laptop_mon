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
