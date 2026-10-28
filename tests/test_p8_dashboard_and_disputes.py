"""
tests/test_p8_dashboard_and_disputes.py — Comprehensive Test Suite for Prompt P8.

Covers:
- REQ-2-1: Employee views own monitoring state and data.
- REQ-2-3: Manager sees only assigned teams.
- REQ-11-3: Employee self-view with monitoring state, policy, and collected data.
- Edge Case E41: Employee moved to another team.
- Edge Case E46: Multi-tenant user switching.
- Edge Case E47: Manager changes teams.
- Edge Case E89: False positive / employee dispute flow.
- Edge Case E99: Optimistic locking on policy updates.
"""

from __future__ import annotations

import datetime
import uuid
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.analytics.models import AppUsageInterval, DailyMetrics, Dispute, DisputeStatus, IntervalState
from apps.audit.models import AuditLog
from apps.devices.models import Device, DeviceStatus
from apps.policies.models import AppClassification, AppRule, MonitoringPolicy
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Team, TeamMember, Tenant, TenantStatus


class P8DashboardAndDisputesTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()

        # Tenant 1 & Tenant 2
        self.tenant_1 = Tenant.objects.create(name="Acme Corp", status=TenantStatus.ACTIVE)
        self.tenant_2 = Tenant.objects.create(name="Wayne Enterprises", status=TenantStatus.ACTIVE)

        # Admin user in Tenant 1
        self.admin_user = User.objects.create_user(email="admin@acme.com", name="Alice Admin")
        self.admin_membership = Membership.objects.create(
            tenant=self.tenant_1,
            user=self.admin_user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        # Manager user in Tenant 1
        self.manager_user = User.objects.create_user(email="manager@acme.com", name="Bob Manager")
        self.manager_membership = Membership.objects.create(
            tenant=self.tenant_1,
            user=self.manager_user,
            role=MembershipRole.MANAGER,
            status=MembershipStatus.ACTIVE,
        )

        # Employee 1 in Tenant 1
        self.emp1_user = User.objects.create_user(email="emp1@acme.com", name="Charlie Emp")
        self.emp1_membership = Membership.objects.create(
            tenant=self.tenant_1,
            user=self.emp1_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        # Employee 2 in Tenant 1
        self.emp2_user = User.objects.create_user(email="emp2@acme.com", name="Dana Emp")
        self.emp2_membership = Membership.objects.create(
            tenant=self.tenant_1,
            user=self.emp2_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        # Teams in Tenant 1
        self.team_alpha = Team.objects.create(tenant=self.tenant_1, name="Alpha Team")
        self.team_beta = Team.objects.create(tenant=self.tenant_1, name="Beta Team")

        # Assign Manager & Emp1 to Team Alpha
        TeamMember.objects.create(team=self.team_alpha, membership=self.manager_membership)
        TeamMember.objects.create(team=self.team_alpha, membership=self.emp1_membership)

        # Assign Emp2 to Team Beta
        TeamMember.objects.create(team=self.team_beta, membership=self.emp2_membership)

        # Devices for Emp1 and Emp2
        self.device_emp1 = Device.objects.create(
            tenant=self.tenant_1,
            membership=self.emp1_membership,
            hostname="ACME-EMP1-LAPTOP",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )
        self.device_emp2 = Device.objects.create(
            tenant=self.tenant_1,
            membership=self.emp2_membership,
            hostname="ACME-EMP2-LAPTOP",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )

        # Metrics for Emp1 and Emp2
        self.metric_emp1 = DailyMetrics.objects.create(
            tenant=self.tenant_1,
            device=self.device_emp1,
            local_date=timezone.now().date(),
            observed_session_seconds=28800,
            active_seconds=21600,
            idle_seconds=7200,
            productive_seconds=18000,
            neutral_seconds=1800,
            distracting_seconds=1800,
            productive_share=83.33,
            monitoring_coverage=100.0,
            calc_version=1,
            data_freshness_at=timezone.now(),
        )
        self.metric_emp2 = DailyMetrics.objects.create(
            tenant=self.tenant_1,
            device=self.device_emp2,
            local_date=timezone.now().date(),
            observed_session_seconds=28800,
            active_seconds=14400,
            idle_seconds=14400,
            productive_seconds=10800,
            neutral_seconds=1800,
            distracting_seconds=1800,
            productive_share=75.0,
            monitoring_coverage=100.0,
            calc_version=1,
            data_freshness_at=timezone.now(),
        )

    def _auth_client(self, user: User, tenant: Tenant) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # ── REQ-2-1 & REQ-11-3: Employee Self-View ────────────────────────────────

    def test_REQ_2_1_and_REQ_11_3_employee_self_view(self) -> None:
        """Employee can query self-view to see own devices, effective policy, metrics, and privacy principles."""
        client = self._auth_client(self.emp1_user, self.tenant_1)
        res = client.get("/api/reports/self-view")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["employee"]["email"], "emp1@acme.com")
        self.assertEqual(data["employee"]["tenant_name"], "Acme Corp")
        self.assertTrue(data["monitoring_state"]["active"])
        self.assertEqual(len(data["monitoring_state"]["devices"]), 1)
        self.assertEqual(data["monitoring_state"]["devices"][0]["hostname"], "ACME-EMP1-LAPTOP")

        # Privacy notice principles
        principles = data["privacy_notice"]["transparency_principles"]
        self.assertTrue(any("No keystroke logging" in p for p in principles))
        self.assertTrue(any("explicit gap" in p for p in principles))

        # Recent metrics belong strictly to Emp1
        self.assertEqual(len(data["recent_metrics"]), 1)
        self.assertEqual(str(data["recent_metrics"][0]["device_id"]), str(self.device_emp1.id))

    # ── REQ-2-3: Manager Scoping ──────────────────────────────────────────────

    def test_REQ_2_3_manager_sees_only_assigned_teams(self) -> None:
        """Manager only sees metrics and devices for members of their assigned team (Team Alpha)."""
        client = self._auth_client(self.manager_user, self.tenant_1)
        res = client.get("/api/reports/daily")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Should contain metric for emp1 (Team Alpha), but NEVER emp2 (Team Beta)
        device_ids = [m["device_id"] for m in res.data["results"]]
        self.assertIn(str(self.device_emp1.id), device_ids)
        self.assertNotIn(str(self.device_emp2.id), device_ids)

    # ── Edge Case E41: Employee Moved to Another Team ─────────────────────────

    def test_E41_employee_moved_to_another_team(self) -> None:
        """When an employee is moved from Team Alpha to Team Beta, Manager loses visibility."""
        client = self._auth_client(self.manager_user, self.tenant_1)

        # Initially manager sees Emp1
        res1 = client.get("/api/reports/daily")
        device_ids_before = [m["device_id"] for m in res1.data["results"]]
        self.assertIn(str(self.device_emp1.id), device_ids_before)

        # Move Emp1 to Team Beta
        TeamMember.objects.filter(membership=self.emp1_membership).delete()
        TeamMember.objects.create(team=self.team_beta, membership=self.emp1_membership)

        # Now manager can no longer see Emp1
        res2 = client.get("/api/reports/daily")
        device_ids_after = [m["device_id"] for m in res2.data["results"]]
        self.assertNotIn(str(self.device_emp1.id), device_ids_after)

    # ── Edge Case E46: User in Multiple Tenants ──────────────────────────────

    def test_E46_user_in_multiple_tenants(self) -> None:
        """User belonging to two tenants switches context seamlessly via X-Tenant-ID."""
        # Create membership for Emp1 in Wayne Enterprises as well
        Membership.objects.create(
            tenant=self.tenant_2,
            user=self.emp1_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        client = APIClient()
        session, raw_token = UserSession.create_session(user=self.emp1_user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")

        # 1. Query under Tenant 1 (Acme Corp)
        client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_1.id)
        res1 = client.get("/api/reports/self-view")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["employee"]["tenant_name"], "Acme Corp")

        # 2. Query under Tenant 2 (Wayne Enterprises)
        client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_2.id)
        res2 = client.get("/api/reports/self-view")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["employee"]["tenant_name"], "Wayne Enterprises")

    # ── Edge Case E47: Manager Changes Teams ─────────────────────────────────

    def test_E47_manager_changes_teams(self) -> None:
        """Manager reassigned from Team Alpha to Team Beta immediately sees Team Beta members."""
        client = self._auth_client(self.manager_user, self.tenant_1)

        # Reassign manager from Alpha to Beta
        TeamMember.objects.filter(membership=self.manager_membership).delete()
        TeamMember.objects.create(team=self.team_beta, membership=self.manager_membership)

        res = client.get("/api/reports/daily")
        device_ids = [m["device_id"] for m in res.data["results"]]
        self.assertNotIn(str(self.device_emp1.id), device_ids)
        self.assertIn(str(self.device_emp2.id), device_ids)

    # ── Edge Case E89: False Positive or Employee Dispute Flow ────────────────

    def test_E89_false_positive_employee_dispute(self) -> None:
        """Employee submits a dispute on app classification; Manager reviews and Admin resolves it."""
        emp_client = self._auth_client(self.emp1_user, self.tenant_1)

        # 1. Employee submits dispute
        payload = {
            "target_app": "slack.exe",
            "target_date": str(timezone.now().date()),
            "reason": "Internal work communication misclassified as distracting.",
            "desired_classification": "productive",
        }
        res_create = emp_client.post("/api/disputes", payload, format="json")
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        dispute_id = res_create.data["id"]
        self.assertEqual(res_create.data["status"], "open")

        # Verify audit log recorded
        audit_entry = AuditLog.objects.filter(action="dispute.created").first()
        self.assertIsNotNone(audit_entry)

        # 2. Manager of Team Alpha can see this dispute
        mgr_client = self._auth_client(self.manager_user, self.tenant_1)
        res_mgr_list = mgr_client.get("/api/disputes")
        self.assertEqual(res_mgr_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_mgr_list.data), 1)

        # 3. Admin resolves the dispute
        admin_client = self._auth_client(self.admin_user, self.tenant_1)
        patch_payload = {
            "status": "resolved",
            "resolution_notes": "Approved: Slack reclassified as productive application.",
        }
        res_resolve = admin_client.patch(f"/api/disputes/{dispute_id}", patch_payload, format="json")
        self.assertEqual(res_resolve.status_code, status.HTTP_200_OK)
        self.assertEqual(res_resolve.data["status"], "resolved")

        # 4. Verify that resolution created an AppRule for slack.exe
        app_rule = AppRule.objects.filter(tenant=self.tenant_1, app_identifier="slack.exe").first()
        self.assertIsNotNone(app_rule)
        self.assertEqual(app_rule.classification, AppClassification.PRODUCTIVE)

    # ── Edge Case E99: Optimistic Locking on Policy Updates ───────────────────

    def test_E99_concurrent_admin_policy_edits_optimistic_locking(self) -> None:
        """Concurrent policy updates detect version conflict and reject stale updates (E99)."""
        admin_client = self._auth_client(self.admin_user, self.tenant_1)
        policy = MonitoringPolicy.get_or_create_default(self.tenant_1)

        # 1. Admin A updates policy with expected version=1 -> succeeds and increments version to 2
        res1 = admin_client.patch(
            f"/api/policies/{policy.id}",
            {"expected_version": policy.version, "idle_threshold_seconds": 240},
            format="json",
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["version"], policy.version + 1)

        # 2. Admin B attempts update with stale expected version=1 -> must be rejected with 409 Conflict
        res2 = admin_client.patch(
            f"/api/policies/{policy.id}",
            {"expected_version": policy.version, "idle_threshold_seconds": 300},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res2.data["code"].lower(), "version_conflict")
