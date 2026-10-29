"""Comprehensive tests for Prompt P1: Tenancy, RBAC, Audit, and Edge Cases E41–E48, E78, E80, E100."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from apps.accounts.models import User, UserSession
from apps.accounts.oidc import generate_oidc_flow_params
from apps.audit.models import AuditLog
from apps.audit.services import log_audit_event
from apps.common.cache import delete_tenant_cache, get_tenant_cache, set_tenant_cache, tenant_cache_key
from apps.rbac.permissions import get_manager_accessible_team_ids
from apps.support_access.models import SupportAccessGrant, SupportAccessStatus
from apps.tenancy.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    TeamMember,
    Tenant,
    TenantStatus,
)
from apps.tenancy.services import change_membership_role, change_membership_team


class P1TenancyRBACAuditTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        # Tenant A (Primary Organization)
        self.tenant_a = Tenant.objects.create(name="Acme Corp", status=TenantStatus.ACTIVE)
        # Tenant B (Secondary Organization for cross-tenant tests)
        self.tenant_b = Tenant.objects.create(name="Beta Inc", status=TenantStatus.ACTIVE)

        # Users
        self.admin_user_a = User.objects.create_user(
            email="admin@acme.com", name="Alice Admin", mfa_enabled=True
        )
        self.manager_user_a = User.objects.create_user(
            email="manager@acme.com", name="Bob Manager", mfa_enabled=False
        )
        self.employee_user_a = User.objects.create_user(
            email="employee@acme.com", name="Charlie Employee", mfa_enabled=False
        )
        self.auditor_user_a = User.objects.create_user(
            email="auditor@acme.com", name="Audrey Auditor", mfa_enabled=False
        )
        self.admin_user_b = User.objects.create_user(
            email="admin@beta.com", name="Dave Admin B", mfa_enabled=True
        )

        # Memberships in Tenant A
        self.membership_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_user_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )
        self.membership_manager_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.manager_user_a,
            role=MembershipRole.MANAGER,
            status=MembershipStatus.ACTIVE,
        )
        self.membership_employee_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.employee_user_a,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )
        self.membership_auditor_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.auditor_user_a,
            role=MembershipRole.AUDITOR,
            status=MembershipStatus.ACTIVE,
        )

        # Membership in Tenant B
        self.membership_admin_b = Membership.objects.create(
            tenant=self.tenant_b,
            user=self.admin_user_b,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        # Teams in Tenant A
        self.team_engineering = Team.objects.create(tenant=self.tenant_a, name="Engineering")
        self.team_sales = Team.objects.create(tenant=self.tenant_a, name="Sales")

        # Team in Tenant B
        self.team_beta = Team.objects.create(tenant=self.tenant_b, name="Beta Devs")

        # Assign employee to Engineering
        self.team_member_employee = TeamMember.objects.create(
            team=self.team_engineering, membership=self.membership_employee_a
        )
        # Assign manager to Engineering
        self.team_member_manager = TeamMember.objects.create(
            team=self.team_engineering, membership=self.membership_manager_a
        )

    def _auth_client(self, user: User, tenant: Tenant | None = None) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        if tenant:
            client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # ── Edge Case E41: Employee moved to another team ──────────────────────────
    def test_E41_employee_moved_to_another_team(self) -> None:
        """When an employee moves to another team, access is immediately re-evaluated and audited."""
        # Initial team is Engineering
        current_teams = TeamMember.objects.filter(membership=self.membership_employee_a)
        self.assertEqual(current_teams.count(), 1)
        self.assertEqual(current_teams.first().team, self.team_engineering)

        # Admin moves employee from Engineering to Sales
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)
        response = admin_client.patch(
            f"/api/tenants/{self.tenant_a.id}/members/{self.membership_employee_a.id}",
            data={"team_id": str(self.team_sales.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify team is now Sales and no longer Engineering
        current_teams = TeamMember.objects.filter(membership=self.membership_employee_a)
        self.assertEqual(current_teams.count(), 1)
        self.assertEqual(current_teams.first().team, self.team_sales)

        # Verify audit log recorded the team change
        audit_entry = AuditLog.objects.filter(
            tenant=self.tenant_a,
            action="membership.team_changed",
            resource_id=str(self.membership_employee_a.id),
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.metadata["new_team"], "Sales")

    # ── Edge Case E42: Employee leaves company ────────────────────────────────
    def test_E42_employee_leaves_company(self) -> None:
        """When an employee leaves, membership is disabled and sessions are immediately revoked."""
        employee_client = self._auth_client(self.employee_user_a, self.tenant_a)

        # Employee can initially view their tenant list
        resp = employee_client.get("/api/me/tenants")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Admin disables employee membership
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)
        patch_resp = admin_client.patch(
            f"/api/tenants/{self.tenant_a.id}/members/{self.membership_employee_a.id}",
            data={"status": "disabled"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        # Membership is now DISABLED
        self.membership_employee_a.refresh_from_db()
        self.assertEqual(self.membership_employee_a.status, MembershipStatus.DISABLED)

        # Employee session was revoked
        active_sessions = UserSession.objects.filter(
            user=self.employee_user_a, revoked_at__isnull=True
        )
        self.assertEqual(active_sessions.count(), 0)

        # Subsequent authenticated requests from this revoked session are rejected
        post_disable_resp = employee_client.get("/api/me/tenants")
        self.assertEqual(post_disable_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        # Audit log entry for disabled membership exists
        audit_entry = AuditLog.objects.filter(
            tenant=self.tenant_a,
            action="membership.disabled",
            resource_id=str(self.membership_employee_a.id),
        ).first()
        self.assertIsNotNone(audit_entry)

    # ── Edge Case E43: Tenant suspended ───────────────────────────────────────
    def test_E43_tenant_suspended(self) -> None:
        """Requests against a suspended tenant are rejected with 403 Forbidden."""
        self.tenant_a.status = TenantStatus.SUSPENDED
        self.tenant_a.save()

        client = self._auth_client(self.admin_user_a, self.tenant_a)
        response = client.get(f"/api/tenants/{self.tenant_a.id}/members")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "tenant_suspended")

    # ── Edge Case E44: Tenant deleted / deleting ──────────────────────────────
    def test_E44_tenant_deleted(self) -> None:
        """Requests against a deleting tenant return a safe 404 Not Found."""
        self.tenant_a.status = TenantStatus.DELETING
        self.tenant_a.save()

        client = self._auth_client(self.admin_user_a, self.tenant_a)
        response = client.get(f"/api/tenants/{self.tenant_a.id}/members")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["code"], "tenant_deleted")

    # ── Edge Case E45: Cross-tenant object ID guessed (IDOR) ───────────────────
    def test_E45_cross_tenant_object_id_guessed(self) -> None:
        """Accessing a foreign tenant's resource returns a safe 404/403 with no leaked details."""
        # Admin from Tenant A tries to query Tenant B members using Tenant A credentials
        admin_a_client = self._auth_client(self.admin_user_a, self.tenant_a)

        # Attempt to access Tenant B's members endpoint
        response = admin_a_client.get(f"/api/tenants/{self.tenant_b.id}/members")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Attempt to access Tenant B by setting Tenant B in X-Tenant-ID
        admin_a_client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_b.id)
        response = admin_a_client.get(f"/api/tenants/{self.tenant_b.id}/members")
        # Middleware blocks foreign tenant lookup with safe 404
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["code"], "not_found")

    # ── Edge Case E46: User in multiple tenants ───────────────────────────────
    def test_E46_user_in_multiple_tenants(self) -> None:
        """A user belonging to multiple organizations must supply an explicit X-Tenant-ID."""
        multi_user = User.objects.create_user(
            email="multi@domain.com", name="Multi Tenant User"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=multi_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )
        Membership.objects.create(
            tenant=self.tenant_b,
            user=multi_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        client = self._auth_client(multi_user)

        # /api/me/tenants works without tenant context to list user's organizations
        list_resp = client.get("/api/me/tenants")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_resp.json()["tenants"]), 2)

        # Calling a tenant-scoped endpoint without X-Tenant-ID returns 400 Bad Request
        resp_no_header = client.get(f"/api/tenants/{self.tenant_a.id}/members")
        self.assertEqual(resp_no_header.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_no_header.json()["code"], "tenant_context_required")

        # Supplying valid explicit X-Tenant-ID successfully routes request to Tenant A
        client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        resp_with_header = client.get("/api/audit-logs/")
        # Employee cannot view audit logs, but tenant was successfully resolved and returned 403 Forbidden by RBAC
        self.assertEqual(resp_with_header.status_code, status.HTTP_403_FORBIDDEN)

    # ── Edge Case E47: Manager changes teams ───────────────────────────────────
    def test_E47_manager_changes_teams(self) -> None:
        """When a manager changes teams, visibility updates immediately to assigned teams only."""
        # Initially, Manager is assigned to Engineering only
        accessible_teams = get_manager_accessible_team_ids(self.membership_manager_a)
        self.assertIn(self.team_engineering.id, accessible_teams)
        self.assertNotIn(self.team_sales.id, accessible_teams)

        # Reassign manager to Sales
        change_membership_team(
            membership=self.membership_manager_a,
            new_team=self.team_sales,
            actor=self.admin_user_a,
        )

        # Visibility immediately shifts to Sales only
        accessible_teams_updated = get_manager_accessible_team_ids(self.membership_manager_a)
        self.assertNotIn(self.team_engineering.id, accessible_teams_updated)
        self.assertIn(self.team_sales.id, accessible_teams_updated)

        # Audit log exists
        audit_entry = AuditLog.objects.filter(
            tenant=self.tenant_a,
            action="membership.team_changed",
            resource_id=str(self.membership_manager_a.id),
        ).first()
        self.assertIsNotNone(audit_entry)

    # ── Edge Case E48: Admin account compromised / session revocation ─────────
    def test_E48_admin_account_compromised(self) -> None:
        """Immediate session revocation invalidates all user tokens across the system."""
        # Create two active sessions for the admin user
        sess1, token1 = UserSession.create_session(user=self.admin_user_a)
        sess2, token2 = UserSession.create_session(user=self.admin_user_a)

        self.assertTrue(sess1.is_valid)
        self.assertTrue(sess2.is_valid)

        # Authenticate with token1 and invoke revoke-all
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token1}")
        client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)

        response = client.post(
            "/api/auth/session/revoke",
            data={"all": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify all sessions are now marked revoked
        sess1.refresh_from_db()
        sess2.refresh_from_db()
        self.assertFalse(sess1.is_valid)
        self.assertFalse(sess2.is_valid)

        # Both tokens are immediately rejected
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token2}")
        post_revoke_resp = client.get("/api/me/tenants")
        self.assertEqual(post_revoke_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Edge Case E78: Database migration discipline ───────────────────────────
    def test_E78_database_migration_fails(self) -> None:
        """Migration CI gate verifies no destructive operations exist without approved markers."""
        from scripts.check_migrations import check_migration_file

        repo_root = Path(__file__).resolve().parent.parent
        migration_files = list(repo_root.glob("backend/apps/*/migrations/*.py"))
        migration_files = [f for f in migration_files if f.name != "__init__.py"]

        self.assertGreater(len(migration_files), 0)
        for mf in migration_files:
            violations = check_migration_file(mf)
            self.assertEqual(
                violations,
                [],
                f"Migration {mf} contains unapproved destructive operations: {violations}",
            )

    # ── Edge Case E80: Stale or cross-tenant cache ─────────────────────────────
    def test_E80_stale_or_cross_tenant_cache(self) -> None:
        """Tenant cache keys are strictly isolated; setting data in Tenant A cannot be read in Tenant B."""
        key_name = "team_summary"

        set_tenant_cache(self.tenant_a.id, key_name, {"members": 42})
        set_tenant_cache(self.tenant_b.id, key_name, {"members": 10})

        # Cache partition check
        self.assertEqual(get_tenant_cache(self.tenant_a.id, key_name), {"members": 42})
        self.assertEqual(get_tenant_cache(self.tenant_b.id, key_name), {"members": 10})

        # Key structure validation
        self.assertIn(str(self.tenant_a.id), tenant_cache_key(self.tenant_a.id, key_name))
        self.assertIn(str(self.tenant_b.id), tenant_cache_key(self.tenant_b.id, key_name))
        self.assertNotEqual(
            tenant_cache_key(self.tenant_a.id, key_name),
            tenant_cache_key(self.tenant_b.id, key_name),
        )

        # Deletion from Tenant A does not clear Tenant B
        delete_tenant_cache(self.tenant_a.id, key_name)
        self.assertIsNone(get_tenant_cache(self.tenant_a.id, key_name))
        self.assertEqual(get_tenant_cache(self.tenant_b.id, key_name), {"members": 10})

    # ── Edge Case E100: Support staff accesses customer data ───────────────────
    def test_E100_support_staff_accesses_customer_data(self) -> None:
        """Support staff requires JIT request, Org Admin approval, time-bound grant, and full audit."""
        support_user = User.objects.create_user(
            email="support.agent@platform.local", name="Sam Support"
        )
        support_client = self._auth_client(support_user)

        # 1. Support agent requests JIT access
        req_resp = support_client.post(
            "/api/support-access/request",
            data={
                "tenant": str(self.tenant_a.id),
                "reason": "Investigating ticket #4810 sync discrepancy",
            },
            format="json",
        )
        self.assertEqual(req_resp.status_code, status.HTTP_201_CREATED)
        grant_id = req_resp.json()["id"]

        grant = SupportAccessGrant.objects.get(id=grant_id)
        self.assertEqual(grant.status, SupportAccessStatus.PENDING)
        self.assertFalse(grant.is_valid)

        # 2. Org Admin approves request for 2 hours
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)
        approve_resp = admin_client.post(
            f"/api/support-access/{grant_id}/approve",
            data={"duration_hours": 2},
            format="json",
        )
        self.assertEqual(approve_resp.status_code, status.HTTP_200_OK)

        grant.refresh_from_db()
        self.assertEqual(grant.status, SupportAccessStatus.APPROVED)
        self.assertTrue(grant.is_valid)
        self.assertEqual(grant.approved_by, self.admin_user_a)

        # 3. Revoke access
        revoke_resp = admin_client.post(f"/api/support-access/{grant_id}/revoke")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)

        grant.refresh_from_db()
        self.assertEqual(grant.status, SupportAccessStatus.REVOKED)
        self.assertFalse(grant.is_valid)

        # 4. Verify audit entries
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant_a, action="support_access.requested"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant_a, action="support_access.approved"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant_a, action="support_access.revoked"
            ).exists()
        )

    # ── Append-Only Audit Log Invariants ──────────────────────────────────────
    def test_audit_log_append_only_protection(self) -> None:
        """Audit logs cannot be updated or deleted at the ORM level."""
        entry = log_audit_event(
            tenant=self.tenant_a,
            actor=self.admin_user_a,
            action="test.action",
            resource_type="tenant",
            resource_id=str(self.tenant_a.id),
        )

        # Save/update attempt must raise PermissionDenied
        entry.action = "tampered.action"
        with self.assertRaises(PermissionDenied):
            entry.save()

        # Delete attempt must raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            entry.delete()

        # Queryset update attempt must raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.filter(id=entry.id).update(action="tampered")

        # Queryset delete attempt must raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.filter(id=entry.id).delete()

    # ── Composite Constraint: TeamMember Tenant Integrity ────────────────────
    def test_team_member_composite_tenant_constraint(self) -> None:
        """A team member must belong to the exact same tenant as the team."""
        # Attempt to add Tenant A membership to Tenant B's team
        invalid_member = TeamMember(
            team=self.team_beta,  # Tenant B
            membership=self.membership_employee_a,  # Tenant A
        )
        with self.assertRaises(ValidationError):
            invalid_member.clean()

    # ── Role Matrix Tests ─────────────────────────────────────────────────────
    def test_role_matrix_audit_logs_access(self) -> None:
        """Auditors and Org Admins can view audit logs; Employees and Managers are forbidden."""
        # Log a test action
        log_audit_event(
            tenant=self.tenant_a,
            actor=self.admin_user_a,
            action="policy.created",
            resource_type="policy",
            resource_id="pol-1",
        )

        # Admin can view
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)
        self.assertEqual(admin_client.get("/api/audit-logs/").status_code, status.HTTP_200_OK)

        # Auditor can view
        auditor_client = self._auth_client(self.auditor_user_a, self.tenant_a)
        self.assertEqual(auditor_client.get("/api/audit-logs/").status_code, status.HTTP_200_OK)

        # Manager is forbidden
        manager_client = self._auth_client(self.manager_user_a, self.tenant_a)
        self.assertEqual(manager_client.get("/api/audit-logs/").status_code, status.HTTP_403_FORBIDDEN)

        # Employee is forbidden
        employee_client = self._auth_client(self.employee_user_a, self.tenant_a)
        self.assertEqual(employee_client.get("/api/audit-logs/").status_code, status.HTTP_403_FORBIDDEN)

    # ── Standard Error Contract (§8.1) ────────────────────────────────────────
    def test_error_response_contract_format(self) -> None:
        """Error responses adhere strictly to §8.1 schema: code, message, field_errors, correlation_id."""
        client = APIClient()  # Unauthenticated
        response = client.get("/api/me/tenants")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        data = response.json()
        self.assertIn("code", data)
        self.assertIn("message", data)
        self.assertIn("field_errors", data)
        self.assertIn("correlation_id", data)
        # Verify valid UUID correlation ID
        uuid.UUID(data["correlation_id"])

    # ── OIDC Flow & MFA Challenges (§8.2, §11.1) ──────────────────────────────
    def test_oidc_callback_success(self) -> None:
        """OIDC callback validates state and nonce, provisions user, issues session token, and audits login."""
        flow_params = generate_oidc_flow_params()

        response = self.client.post(
            "/api/auth/oidc/callback",
            data={
                "code": "auth-code-1234",
                "state": flow_params["state"],
                "nonce": flow_params["nonce"],
                "email": "new.employee@acme.com",
                "name": "New Employee",
                "mfa_authenticated": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], "new.employee@acme.com")

        # Verify state/nonce consumed (replay attack fails)
        replay_resp = self.client.post(
            "/api/auth/oidc/callback",
            data={
                "code": "auth-code-1234",
                "state": flow_params["state"],
                "nonce": flow_params["nonce"],
                "email": "new.employee@acme.com",
            },
            format="json",
        )
        self.assertEqual(replay_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oidc_callback_mfa_required_for_privileged_user(self) -> None:
        """Privileged users with MFA enabled must satisfy MFA check upon OIDC sign-in."""
        flow_params = generate_oidc_flow_params()

        # Alice Admin has mfa_enabled=True. Attempting sign-in without MFA verification
        response = self.client.post(
            "/api/auth/oidc/callback",
            data={
                "code": "admin-code-5678",
                "state": flow_params["state"],
                "nonce": flow_params["nonce"],
                "email": self.admin_user_a.email,
                "mfa_authenticated": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "mfa_required")

    # ── Tenant Creation & Invitation Lifecycle (§8.2) ─────────────────────────
    def test_create_tenant_makes_creator_org_admin(self) -> None:
        """Creating an organization automatically makes the creator an Org Admin with screenshot permission."""
        creator = User.objects.create_user(email="founder@startup.io", name="Frank Founder")
        client = self._auth_client(creator)

        response = client.post(
            "/api/tenants",
            data={"name": "Startup IO"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["tenant"]["name"], "Startup IO")
        self.assertEqual(data["membership"]["role"], MembershipRole.ADMIN)
        self.assertTrue(data["membership"]["has_screenshot_permission"])

    def test_tenant_invitation_duplicate_pending_rejected(self) -> None:
        """Inviting an email that already has a pending invite is rejected with conflict."""
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)

        # First invite
        resp1 = admin_client.post(
            f"/api/tenants/{self.tenant_a.id}/invitations",
            data={"email": "future.employee@acme.com", "role": "employee"},
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        # Duplicate invite
        resp2 = admin_client.post(
            f"/api/tenants/{self.tenant_a.id}/invitations",
            data={"email": "future.employee@acme.com", "role": "employee"},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp2.json()["code"], "conflict")

    # ── Password Login Tests (Production Login) ───────────────────────────────
    def test_password_login_success(self) -> None:
        """Valid credentials return a session token, user details, and active tenant."""
        user = User.objects.create_user(
            email="prod.user@acme.com",
            password="SecurePassword123!",
            name="Prod User",
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        response = self.client.post(
            "/api/auth/login",
            data={"email": "prod.user@acme.com", "password": "SecurePassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], "prod.user@acme.com")
        self.assertEqual(data["tenant"]["id"], str(self.tenant_a.id))
        self.assertEqual(data["user"]["role"], "admin")

    def test_password_login_invalid_credentials(self) -> None:
        """Invalid password or unknown email returns 401 Unauthorized."""
        User.objects.create_user(
            email="existing@acme.com",
            password="CorrectPassword123!",
            name="Existing User",
        )

        # Wrong password
        resp_wrong_pw = self.client.post(
            "/api/auth/login",
            data={"email": "existing@acme.com", "password": "WrongPassword"},
            format="json",
        )
        self.assertEqual(resp_wrong_pw.status_code, status.HTTP_401_UNAUTHORIZED)

        # Unknown email
        resp_unknown = self.client.post(
            "/api/auth/login",
            data={"email": "unknown@acme.com", "password": "AnyPassword"},
            format="json",
        )
        self.assertEqual(resp_unknown.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_password_login_disabled_account(self) -> None:
        """Disabled user account cannot authenticate and returns 403 Forbidden."""
        User.objects.create_user(
            email="disabled@acme.com",
            password="SomePassword123!",
            name="Disabled User",
            is_active=False,
        )

        response = self.client.post(
            "/api/auth/login",
            data={"email": "disabled@acme.com", "password": "SomePassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

