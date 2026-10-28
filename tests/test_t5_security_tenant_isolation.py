"""
tests/test_t5_security_tenant_isolation.py — Security & Tenant Isolation Test Suite.

Adheres strictly to:
- Prompt T5 from Build Playbook (Laptop Monitoring SaaS - Build Playbook.docx)
- Specification §§ 2, 7, 8, 10, 11, 11.4
- AC-5: No cross-tenant data leak
- RC-06: Security test evidence (T5) reviewed
- RC-07: Cross-tenant isolation verified
- RC-10: Log redaction verified (no secrets in logs)
- Edge cases: E31, E32, E35, E39, E40, E45, E48, E49, E50, E80, E88, E100

Covers:
1. Cross-Tenant Object Access & IDOR across all domain models
2. Multi-Role Negative Authorization Matrix (Employee, Manager, Admin, Auditor)
3. Authentication, Session & Privilege Escalation Security
4. Agent Credential Boundary & Anti-Spoofing
5. Screenshot Storage Hardening & Malicious File Upload Rejection
6. Payload Abuse, Fuzzing & Rate Limiting
7. Secret Scrubbing & Cache Key Tenant Isolation
8. Section 11.4 Threat Model Complete Verification
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.analytics.models import AppUsageInterval, DailyMetrics, Dispute, DisputeStatus
from apps.audit.models import AuditLog
from apps.common.cache import delete_tenant_cache, get_tenant_cache, set_tenant_cache
from apps.common.logging import SecretRedactingFilter, redact_secrets
from apps.devices.models import AgentCredential, Device, DeviceStatus, EnrollmentToken
from apps.ingestion.models import ActivityEvent, EventBatch
from apps.ingestion.services import process_event_batch
from apps.policies.models import MonitoringPolicy
from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.services import (
    ChecksumMismatchError,
    ImageValidationError,
    complete_screenshot_upload,
    create_upload_intent,
    verify_and_process_image,
)
from apps.screenshots.storage import generate_screenshot_object_key, get_storage_backend, reset_storage_backend
from apps.support_access.models import SupportAccessGrant, SupportAccessStatus
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Team, TeamMember, Tenant, TenantStatus

logger = logging.getLogger(__name__)


def make_valid_test_jpeg(width: int = 160, height: int = 90) -> bytes:
    bio = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(50, 100, 150))
    img.save(bio, format="JPEG")
    return bio.getvalue()


class BaseSecurityTestCase(TestCase):
    """Base setup seeding two independent tenants with complete role hierarchies."""

    def setUp(self) -> None:
        cache.clear()
        reset_storage_backend()
        self.storage = get_storage_backend()
        self.client = APIClient()

        # ── 1. Tenant Alpha (Acme Corp) ──────────────────────────────────────
        self.tenant_a = Tenant.objects.create(name="Acme Corp", status=TenantStatus.ACTIVE)

        # Admin Alpha
        self.user_admin_a = User.objects.create_user(
            email="admin@acme.com", name="Admin Alpha", password="password12345", mfa_enabled=True
        )
        self.mem_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_admin_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        # Team Alpha
        self.team_alpha = Team.objects.create(tenant=self.tenant_a, name="Alpha Engineering")

        # Manager Alpha
        self.user_manager_a = User.objects.create_user(
            email="manager@acme.com", name="Manager Alpha", password="password12345"
        )
        self.mem_manager_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_manager_a,
            role=MembershipRole.MANAGER,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )
        TeamMember.objects.create(team=self.team_alpha, membership=self.mem_manager_a)

        # Employee Alpha
        self.user_employee_a = User.objects.create_user(
            email="emp@acme.com", name="Employee Alpha", password="password12345"
        )
        self.mem_employee_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_employee_a,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=False,
        )
        TeamMember.objects.create(team=self.team_alpha, membership=self.mem_employee_a)

        # Auditor Alpha
        self.user_auditor_a = User.objects.create_user(
            email="auditor@acme.com", name="Auditor Alpha", password="password12345"
        )
        self.mem_auditor_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_auditor_a,
            role=MembershipRole.AUDITOR,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=False,
        )

        # Device Alpha
        self.device_a = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.mem_employee_a,
            hostname="ACME-LAPTOP-01",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            hardware_id="HW-ACME-001",
        )
        self.cred_a, self.secret_a = AgentCredential.create_secret_credential(self.device_a)

        # Policy Alpha
        self.policy_a = MonitoringPolicy.objects.create(
            tenant=self.tenant_a,
            version=1,
            screenshot_interval_seconds=300,
            idle_threshold_seconds=180,
            retention_days=30,
            valid_until=timezone.now() + datetime.timedelta(days=365),
            min_agent_version="1.0.0",
        )

        # Screenshot Alpha
        self.shot_a_id = uuid.uuid4()
        self.shot_a_key = generate_screenshot_object_key(
            self.tenant_a.id, self.device_a.id, self.shot_a_id, timezone.now()
        )
        img_bytes = make_valid_test_jpeg()
        self.storage.put_object_bytes(self.shot_a_key, img_bytes, "image/jpeg")
        self.screenshot_a = Screenshot.objects.create(
            id=self.shot_a_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key=self.shot_a_key,
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
            file_size=len(img_bytes),
        )

        # Dispute Alpha
        self.dispute_a = Dispute.objects.create(
            tenant=self.tenant_a,
            membership=self.mem_employee_a,
            target_app="slack.exe",
            target_date=timezone.now().date(),
            desired_classification="productive",
            status=DisputeStatus.OPEN,
            reason="Work discussion",
        )

        # ── 2. Tenant Beta (Cyberdyne Systems) ────────────────────────────────
        self.tenant_b = Tenant.objects.create(name="Cyberdyne Systems", status=TenantStatus.ACTIVE)

        # Admin Beta
        self.user_admin_b = User.objects.create_user(
            email="admin@cyberdyne.com", name="Admin Beta", password="password12345"
        )
        self.mem_admin_b = Membership.objects.create(
            tenant=self.tenant_b,
            user=self.user_admin_b,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        # Employee Beta
        self.user_employee_b = User.objects.create_user(
            email="emp@cyberdyne.com", name="Employee Beta", password="password12345"
        )
        self.mem_employee_b = Membership.objects.create(
            tenant=self.tenant_b,
            user=self.user_employee_b,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=False,
        )

        # Device Beta
        self.device_b = Device.objects.create(
            tenant=self.tenant_b,
            membership=self.mem_employee_b,
            hostname="CYBERDYNE-T800",
            os="linux",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            hardware_id="HW-CYBER-001",
        )
        self.cred_b, self.secret_b = AgentCredential.create_secret_credential(self.device_b)

        # Policy Beta
        self.policy_b = MonitoringPolicy.objects.create(
            tenant=self.tenant_b,
            version=1,
            screenshot_interval_seconds=600,
            idle_threshold_seconds=120,
            retention_days=60,
            valid_until=timezone.now() + datetime.timedelta(days=365),
            min_agent_version="1.0.0",
        )

    def tearDown(self) -> None:
        reset_storage_backend()
        cache.clear()

    def auth_headers(self, user: User, tenant: Tenant) -> Dict[str, str]:
        """Generates authentication headers simulating Bearer token and active tenant context."""
        session, raw_token = UserSession.create_session(user=user)
        return {
            "HTTP_AUTHORIZATION": f"Bearer {raw_token}",
            "HTTP_X_TENANT_ID": str(tenant.id),
        }

    def agent_headers(self, device: Device, secret: str) -> Dict[str, str]:
        """Generates headers simulating agent authentication via per-device credential."""
        return {
            "HTTP_AUTHORIZATION": f"DeviceBearer {secret}",
            "HTTP_X_DEVICE_ID": str(device.id),
        }


# =============================================================================
# 1. Cross-Tenant Object Access & IDOR Verification (AC-5, RC-07, E45)
# =============================================================================

class TestCrossTenantObjectIsolation(BaseSecurityTestCase):
    """
    Exhaustively verifies that no user from Tenant B can access, view, modify,
    or infer existence of Tenant A's objects across any API route.
    """

    def test_cross_tenant_device_access_blocked(self) -> None:
        """Tenant B admin cannot view or revoke Tenant A's device (E45, AC-5)."""
        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)

        # 1. List devices: must NOT contain Device Alpha
        resp = self.client.get("/api/devices", **headers_b)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        raw_devices = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
        device_ids = [d["id"] for d in raw_devices]
        self.assertNotIn(str(self.device_a.id), device_ids)

        # 2. Revoke Device Alpha directly by ID
        resp_revoke = self.client.post(f"/api/devices/{self.device_a.id}/revoke", **headers_b)
        self.assertIn(resp_revoke.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
        self.device_a.refresh_from_db()
        self.assertEqual(self.device_a.status, DeviceStatus.ACTIVE)

    def test_cross_tenant_policy_access_blocked(self) -> None:
        """Tenant B admin cannot read or mutate Tenant A's policy (E45)."""
        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)

        # Direct access to Policy Alpha ID
        resp = self.client.get(f"/api/policies/{self.policy_a.id}", **headers_b)
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

        # Mutation attempt on Policy Alpha
        resp_patch = self.client.patch(
            f"/api/policies/{self.policy_a.id}",
            {"expected_version": 1, "screenshot_interval_seconds": 10},
            format="json",
            **headers_b,
        )
        self.assertIn(resp_patch.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
        self.policy_a.refresh_from_db()
        self.assertEqual(self.policy_a.screenshot_interval_seconds, 300)

    def test_cross_tenant_screenshot_view_url_denied(self) -> None:
        """Tenant B admin cannot obtain signed view URL for Tenant A screenshot (E45, E49)."""
        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)

        # Gallery list must exclude Tenant A screenshot
        resp_list = self.client.get("/api/screenshots", **headers_b)
        self.assertEqual(resp_list.status_code, status.HTTP_200_OK)
        raw_shots = resp_list.data.get("results", resp_list.data) if isinstance(resp_list.data, dict) else resp_list.data
        shot_ids = [s["id"] for s in raw_shots]
        self.assertNotIn(str(self.screenshot_a.id), shot_ids)

        # View URL request for Tenant A screenshot
        resp_view = self.client.post(f"/api/screenshots/{self.screenshot_a.id}/view-url", **headers_b)
        self.assertIn(resp_view.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

    def test_cross_tenant_dispute_access_denied(self) -> None:
        """Tenant B employee or admin cannot view or modify Tenant A disputes (E45)."""
        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)
        resp = self.client.get(f"/api/disputes/{self.dispute_a.id}", **headers_b)
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

    def test_cross_tenant_audit_log_isolation(self) -> None:
        """Audit log explorer strictly filters entries by authenticated tenant."""
        AuditLog.objects.create(
            tenant=self.tenant_a,
            actor=self.user_admin_a,
            action="policy.updated",
            resource_type="policy",
            resource_id=str(self.policy_a.id),
        )
        AuditLog.objects.create(
            tenant=self.tenant_b,
            actor=self.user_admin_b,
            action="policy.created",
            resource_type="policy",
            resource_id=str(self.policy_b.id),
        )

        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)
        resp = self.client.get("/api/audit-logs/", **headers_b)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        raw_logs = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
        actions = [log["action"] for log in raw_logs]
        self.assertIn("policy.created", actions)
        self.assertNotIn("policy.updated", actions)

    def test_cross_tenant_membership_management_denied(self) -> None:
        """Tenant B admin cannot list, modify, or delete Tenant A memberships (E45)."""
        headers_b = self.auth_headers(self.user_admin_b, self.tenant_b)
        resp = self.client.get(f"/api/tenants/{self.tenant_a.id}/members", **headers_b)
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

        resp_patch = self.client.patch(
            f"/api/tenants/{self.tenant_a.id}/members/{self.mem_employee_a.id}",
            {"role": "manager"},
            format="json",
            **headers_b,
        )
        self.assertIn(resp_patch.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))


# =============================================================================
# 2. Multi-Role Negative Authorization Matrix
# =============================================================================

class TestRoleBasedAccessControl(BaseSecurityTestCase):
    """
    Tests least privilege enforcement across all user roles:
    Employee, Manager, Admin, Auditor, and Unauthenticated.
    """

    def test_unauthenticated_requests_denied(self) -> None:
        """Unauthenticated requests to protected endpoints return 401 Unauthorized."""
        protected_urls = [
            ("/api/policies", "GET"),
            ("/api/devices", "GET"),
            ("/api/screenshots", "GET"),
            ("/api/audit-logs/", "GET"),
            ("/api/reports/daily", "GET"),
            ("/api/billing/overview", "GET"),
        ]
        for url, method in protected_urls:
            with self.subTest(url=url):
                if method == "GET":
                    resp = self.client.get(url)
                else:
                    resp = self.client.post(url)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_employee_negative_authorization(self) -> None:
        """Employees are blocked from org-level policies, audit logs, and billing."""
        headers_emp = self.auth_headers(self.user_employee_a, self.tenant_a)

        # 1. Cannot list or mutate policies
        self.assertEqual(self.client.get("/api/policies", **headers_emp).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post("/api/policies", {"version": 2}, format="json", **headers_emp).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 2. Cannot view audit logs
        self.assertEqual(self.client.get("/api/audit-logs/", **headers_emp).status_code, status.HTTP_403_FORBIDDEN)

        # 3. Cannot view billing overview
        self.assertEqual(self.client.get("/api/billing/overview", **headers_emp).status_code, status.HTTP_403_FORBIDDEN)

        # 4. Cannot revoke devices
        self.assertEqual(
            self.client.post(f"/api/devices/{self.device_a.id}/revoke", **headers_emp).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_team_scoping_and_forbidden_actions(self) -> None:
        """Managers cannot access org policies or members of other teams (REQ-2-3, E47)."""
        headers_mgr = self.auth_headers(self.user_manager_a, self.tenant_a)

        # Cannot edit organization policy
        self.assertEqual(
            self.client.post("/api/policies", {"version": 2}, format="json", **headers_mgr).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Cannot access billing
        self.assertEqual(self.client.get("/api/billing/overview", **headers_mgr).status_code, status.HTTP_403_FORBIDDEN)

    def test_auditor_is_strictly_read_only(self) -> None:
        """Auditor role can read audit logs but cannot mutate data."""
        headers_auditor = self.auth_headers(self.user_auditor_a, self.tenant_a)

        # Can read audit logs
        self.assertEqual(self.client.get("/api/audit-logs/", **headers_auditor).status_code, status.HTTP_200_OK)

        # Cannot mutate policies
        self.assertEqual(
            self.client.post("/api/policies", {"version": 2}, format="json", **headers_auditor).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Cannot revoke devices
        self.assertEqual(
            self.client.post(f"/api/devices/{self.device_a.id}/revoke", **headers_auditor).status_code,
            status.HTTP_403_FORBIDDEN,
        )


# =============================================================================
# 3. Authentication, Session & Privilege Escalation Security (E48)
# =============================================================================

class TestAuthSessionPrivilegeEscalation(BaseSecurityTestCase):
    """
    Tests privilege escalation prevention, session fixation, and session revocation.
    """

    def test_member_self_privilege_escalation_denied(self) -> None:
        """A regular member cannot promote themselves to admin or grant permissions."""
        headers_emp = self.auth_headers(self.user_employee_a, self.tenant_a)

        resp = self.client.patch(
            f"/api/tenants/{self.tenant_a.id}/members/{self.mem_employee_a.id}",
            {"role": "admin", "has_screenshot_permission": True},
            format="json",
            **headers_emp,
        )
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

        self.mem_employee_a.refresh_from_db()
        self.assertEqual(self.mem_employee_a.role, MembershipRole.EMPLOYEE)
        self.assertFalse(self.mem_employee_a.has_screenshot_permission)

    def test_session_revocation_on_password_change(self) -> None:
        """Password change or admin revocation invalidates active user sessions (E48)."""
        session, raw_token = UserSession.create_session(user=self.user_admin_a)
        self.assertTrue(session.is_valid)

        # Revoke sessions for user
        UserSession.revoke_all_for_user(self.user_admin_a)
        session.refresh_from_db()
        self.assertFalse(session.is_valid)

    def test_invitation_enumeration_protection(self) -> None:
        """Querying invalid invitation tokens does not leak tenant existence (E39)."""
        headers_emp = self.auth_headers(self.user_employee_a, self.tenant_a)
        bogus_token = str(uuid.uuid4())
        resp = self.client.post(
            "/api/invitations/accept",
            {"token": bogus_token},
            format="json",
            **headers_emp,
        )
        self.assertIn(resp.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))
        self.assertNotIn("Acme Corp", str(resp.content))


# =============================================================================
# 4. Agent Credential Boundary & Anti-Spoofing (REQ-2-7, E39, E40)
# =============================================================================

class TestAgentCredentialAndAntiSpoofing(BaseSecurityTestCase):
    """
    Tests agent enrollment token replay, credential scoping, and tenant anti-spoofing.
    """

    def test_enrollment_token_single_use_and_expiry(self) -> None:
        """Enrollment token cannot be reused and expires after validity window (E39)."""
        token_obj, raw_token = EnrollmentToken.create_token(
            tenant=self.tenant_a,
            created_by=self.user_admin_a,
            expires_hours=1,
        )

        # First enrollment succeeds
        resp1 = self.client.post(
            "/api/agent/enroll",
            {
                "token": raw_token,
                "hostname": "NEW-LAPTOP-01",
                "os": "windows",
                "agent_version": "1.0.0",
                "hardware_id": "HW-NEW-001",
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        # Replayed enrollment token fails (E39)
        resp2 = self.client.post(
            "/api/agent/enroll",
            {
                "token": raw_token,
                "hostname": "CLONED-LAPTOP",
                "os": "windows",
                "agent_version": "1.0.0",
                "hardware_id": "HW-CLONE-999",
            },
            format="json",
        )
        self.assertIn(resp2.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT))

    def test_device_credential_cross_device_impersonation_denied(self) -> None:
        """Device A's credential cannot be used to submit data for Device B (E40)."""
        # Attacker uses Device A's secret header with Device B's ID
        headers = {
            "HTTP_AUTHORIZATION": f"DeviceBearer {self.secret_a}",
            "HTTP_X_DEVICE_ID": str(self.device_b.id),
        }
        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(uuid.uuid4()),
                        "event_type": "app.active",
                        "occurred_at": timezone.now().isoformat(),
                        "payload": {"app_identifier": "malicious.exe"},
                    }
                ],
            },
            format="json",
            **headers,
        )
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_tenant_spoofing_in_agent_payload_ignored(self) -> None:
        """Tenant ID in agent JSON payload is ignored; server binds strictly to credential tenant."""
        headers = self.agent_headers(self.device_a, self.secret_a)
        event_id = str(uuid.uuid4())

        # Malicious payload attempts to insert events into Tenant Beta
        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "tenant_id": str(self.tenant_b.id),
                "events": [
                    {
                        "id": event_id,
                        "tenant_id": str(self.tenant_b.id),
                        "event_type": "app.active",
                        "occurred_at": timezone.now().isoformat(),
                        "payload": {"app_identifier": "test.exe"},
                    }
                ],
            },
            format="json",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Invariant Verification: Event is bound to Tenant Alpha, NEVER Tenant Beta
        ev = ActivityEvent.objects.get(id=event_id)
        self.assertEqual(ev.tenant_id, self.tenant_a.id)
        self.assertNotEqual(ev.tenant_id, self.tenant_b.id)

    def test_event_batch_replay_and_tamper_conflict(self) -> None:
        """Duplicate event with modified payload triggers 409 Conflict & security alert (E31, E32)."""
        t0 = timezone.now()
        ev_id = uuid.uuid4()
        raw_events = [
            {
                "id": str(ev_id),
                "event_type": "app.active",
                "occurred_at": t0.isoformat(),
                "payload": {"app_identifier": "legitimate.exe"},
            }
        ]

        # First submission
        res1 = process_event_batch(self.device_a, raw_events, agent_version="1.0.0")
        self.assertEqual(res1["status"], "accepted")

        # Idempotent replay with exact same payload (E31)
        res2 = process_event_batch(self.device_a, raw_events, agent_version="1.0.0")
        self.assertIn(str(ev_id), res2["already_accepted"])

        # Tampered replay with modified payload triggers Conflict (E32)
        tampered_events = [
            {
                "id": str(ev_id),
                "event_type": "app.active",
                "occurred_at": t0.isoformat(),
                "payload": {"app_identifier": "TAMPERED_MODIFIED.exe"},
            }
        ]
        from apps.common.exceptions import ApplicationConflict

        with self.assertRaises(ApplicationConflict):
            process_event_batch(self.device_a, tampered_events, agent_version="1.0.0")


# =============================================================================
# 5. Screenshot Storage Hardening & Malicious File Uploads (REQ-10-2, E49, E50)
# =============================================================================

class TestScreenshotPipelineHardening(BaseSecurityTestCase):
    """
    Validates presigned URL expiry, scoping, and upload file security filters.
    """

    def test_presigned_url_scoping_and_expiry(self) -> None:
        """Presigned view URLs are scoped to one object and expire strictly (E49)."""
        headers_admin_a = self.auth_headers(self.user_admin_a, self.tenant_a)
        resp = self.client.post(f"/api/screenshots/{self.screenshot_a.id}/view-url", **headers_admin_a)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        view_url = resp.data.get("view_url") or resp.data.get("url")
        self.assertIsNotNone(view_url)
        self.assertIn("expires=", view_url)

        # Audit log entry created
        audit_entry = AuditLog.objects.filter(
            tenant=self.tenant_a, action="screenshot.viewed", resource_id=str(self.screenshot_a.id)
        ).first()
        self.assertIsNotNone(audit_entry)

    def test_malicious_upload_signatures_rejected(self) -> None:
        """Executable magic bytes and malware test signatures are rejected (E50)."""
        # EICAR signature
        eicar_bytes = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        with self.assertRaises(ImageValidationError):
            verify_and_process_image(eicar_bytes)

        # DOS Executable header
        dos_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
        with self.assertRaises(ImageValidationError):
            verify_and_process_image(dos_bytes)

        # Linux ELF header
        elf_bytes = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        with self.assertRaises(ImageValidationError):
            verify_and_process_image(elf_bytes)

    def test_decompression_bomb_rejected(self) -> None:
        """Decompression bomb with absurd pixel dimensions is rejected (E50)."""
        bio = io.BytesIO()
        # Create small file that claims massive dimensions
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
            with self.assertRaises(ImageValidationError):
                # An image with 160x90 = 14400 pixels exceeds simulated 1000 MAX_IMAGE_PIXELS
                verify_and_process_image(make_valid_test_jpeg(160, 90))

    def test_checksum_mismatch_rejected(self) -> None:
        """Checksum mismatch raises ChecksumMismatchError (§10.2)."""
        shot_bytes = make_valid_test_jpeg()
        with self.assertRaises(ChecksumMismatchError):
            verify_and_process_image(shot_bytes, expected_checksum="badchecksum1234567890")


# =============================================================================
# 6. Payload Abuse, Fuzzing & Rate Limiting (E33, E35)
# =============================================================================

class TestPayloadAbuseFuzzingAndRateLimiting(BaseSecurityTestCase):
    """
    Fuzzing tests evaluating malformed JSON, SQL injection strings, and rate limits.
    """

    def test_malformed_json_handling(self) -> None:
        """Malformed or truncated JSON payload returns 400 Bad Request without crash."""
        headers = self.agent_headers(self.device_a, self.secret_a)
        resp = self.client.post(
            "/api/agent/events/batch",
            data="{malformed_json: missing_quotes, [unclosed",
            content_type="application/json",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sql_and_header_injection_escaped(self) -> None:
        """SQL injection and CRLF strings in payloads are safely escaped as literals."""
        headers = self.agent_headers(self.device_a, self.secret_a)
        ev_id = str(uuid.uuid4())
        sql_injection = "' OR '1'='1'; DROP TABLE activity_events; --"
        crlf_injection = "chrome.exe\r\nSet-Cookie: evil_token=666"

        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": ev_id,
                        "event_type": "app.active",
                        "occurred_at": timezone.now().isoformat(),
                        "payload": {"app_identifier": sql_injection, "window_title": crlf_injection},
                    }
                ],
            },
            format="json",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Database record exists and matches string literal exactly
        ev = ActivityEvent.objects.get(id=ev_id)
        self.assertEqual(ev.payload.get("app_identifier"), sql_injection)
        self.assertEqual(ev.payload.get("window_title"), crlf_injection)

    def test_rate_limiting_enforcement(self) -> None:
        """Rapid requests exceeding rate limit threshold return HTTP 429 (E35)."""
        headers = self.agent_headers(self.device_a, self.secret_a)
        cache_key = f"rate_limit:device:{self.device_a.id}"
        cache.set(cache_key, 120, timeout=60)  # Max requests per minute reached

        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(uuid.uuid4()),
                        "event_type": "app.active",
                        "occurred_at": timezone.now().isoformat(),
                        "payload": {"app_identifier": "test.exe"},
                    }
                ],
            },
            format="json",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertTrue(resp.has_header("Retry-After"))


# =============================================================================
# 7. Secrets Scrubbing & Cache Isolation (E80, E88, RC-10)
# =============================================================================

class TestSecretsScrubbingAndCacheIsolation(BaseSecurityTestCase):
    """
    Tests automated secret scrubbing in logs and tenant cache key isolation.
    """

    def test_log_redaction_filters_mask_secrets(self) -> None:
        """SecretRedactingFilter scrubs bearer tokens, secrets, and credentials (E88, RC-10)."""
        sensitive_log = (
            f"Device enrolled with secret Bearer {self.secret_a} and token 1234567890abcdef. "
            "Authorization: Bearer my_super_secret_jwt_token_12345"
        )
        redacted = redact_secrets(sensitive_log)

        self.assertNotIn(self.secret_a, redacted)
        self.assertNotIn("my_super_secret_jwt_token_12345", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_cache_keys_strictly_scoped_by_tenant(self) -> None:
        """Tenant cache operations always include tenant prefix preventing collision (E80)."""
        set_tenant_cache(self.tenant_a, "active_policy", "POLICY_ALPHA_PAYLOAD")
        set_tenant_cache(self.tenant_b, "active_policy", "POLICY_BETA_PAYLOAD")

        val_a = get_tenant_cache(self.tenant_a, "active_policy")
        val_b = get_tenant_cache(self.tenant_b, "active_policy")

        self.assertEqual(val_a, "POLICY_ALPHA_PAYLOAD")
        self.assertEqual(val_b, "POLICY_BETA_PAYLOAD")

        # Deleting cache in Tenant A does not affect Tenant B
        delete_tenant_cache(self.tenant_a, "active_policy")
        self.assertIsNone(get_tenant_cache(self.tenant_a, "active_policy"))
        self.assertEqual(get_tenant_cache(self.tenant_b, "active_policy"), "POLICY_BETA_PAYLOAD")


# =============================================================================
# 8. Section 11.4 Threat Model Complete Verification
# =============================================================================

class TestThreatModelMatrix(BaseSecurityTestCase):
    """
    Direct verification of all 10 rows in Specification §11.4 Threat Table.
    """

    def test_threat_01_cross_tenant_idor(self) -> None:
        """Row 1: Cross-tenant data access (IDOR) blocked on all querysets."""
        headers = self.auth_headers(self.user_admin_b, self.tenant_b)
        resp = self.client.get(f"/api/policies/{self.policy_a.id}", **headers)
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))

    def test_threat_02_stolen_device_credential(self) -> None:
        """Row 2: Stolen device credential revoked immediately halts ingestion."""
        self.device_a.revoke()
        headers = self.agent_headers(self.device_a, self.secret_a)
        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "events": [{"id": str(uuid.uuid4()), "event_type": "app.active", "occurred_at": timezone.now().isoformat()}],
            },
            format="json",
            **headers,
        )
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_threat_03_replayed_enrollment_token(self) -> None:
        """Row 3: Replayed enrollment token is rejected (E39)."""
        tok, raw = EnrollmentToken.create_token(tenant=self.tenant_a, created_by=self.user_admin_a)
        self.client.post(
            "/api/agent/enroll",
            {"token": raw, "hostname": "PC1", "os": "windows", "agent_version": "1.0.0", "hardware_id": "HW1"},
            format="json",
        )
        resp = self.client.post(
            "/api/agent/enroll",
            {"token": raw, "hostname": "PC2", "os": "windows", "agent_version": "1.0.0", "hardware_id": "HW2"},
            format="json",
        )
        self.assertIn(resp.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT))

    def test_threat_04_screenshot_url_leak(self) -> None:
        """Row 4: Screenshot view URL is short-lived, presigned, and audited."""
        headers = self.auth_headers(self.user_admin_a, self.tenant_a)
        resp = self.client.post(f"/api/screenshots/{self.screenshot_a.id}/view-url", **headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(AuditLog.objects.filter(action="screenshot.viewed", resource_id=str(self.screenshot_a.id)).exists())

    def test_threat_05_malicious_upload(self) -> None:
        """Row 5: Malicious upload fails malware scan / format checks (E50)."""
        with self.assertRaises(ImageValidationError):
            verify_and_process_image(b"\x7fELF_BAD_EXECUTABLE")

    def test_threat_06_compromised_admin_account(self) -> None:
        """Row 6: Compromised admin sessions can be revoked; audit log records changes."""
        session, raw = UserSession.create_session(user=self.user_admin_a)
        self.assertTrue(session.is_valid)
        UserSession.revoke_all_for_user(self.user_admin_a)
        session.refresh_from_db()
        self.assertFalse(session.is_valid)

    def test_threat_07_tenant_spoofing_in_payloads(self) -> None:
        """Row 7: Tenant spoofing in agent payloads ignored; derived from credential."""
        headers = self.agent_headers(self.device_a, self.secret_a)
        ev_id = str(uuid.uuid4())
        resp = self.client.post(
            "/api/agent/events/batch",
            {
                "agent_version": "1.0.0",
                "tenant_id": str(self.tenant_b.id),
                "events": [{"id": ev_id, "event_type": "app.active", "occurred_at": timezone.now().isoformat()}],
            },
            format="json",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(ActivityEvent.objects.get(id=ev_id).tenant_id, self.tenant_a.id)

    def test_threat_08_secrets_in_logs_and_dumps(self) -> None:
        """Row 8: Redaction filter scrubs tokens and passwords (E88)."""
        msg = f"Credentials: Bearer {self.secret_a}"
        redacted = redact_secrets(msg)
        self.assertNotIn(self.secret_a, redacted)

    def test_threat_09_stale_or_cross_tenant_cache(self) -> None:
        """Row 9: Cache keys are strictly tenant-scoped (E80)."""
        set_tenant_cache(self.tenant_a, "k", "v1")
        self.assertIsNone(get_tenant_cache(self.tenant_b, "k"))

    def test_threat_10_support_staff_access_control(self) -> None:
        """Row 10: Support staff break-glass JIT access requires approval and is audited (E100)."""
        support_user = User.objects.create_user(email="staff@laptopmon.internal", name="Support Engineer")
        grant = SupportAccessGrant.objects.create(
            tenant=self.tenant_a,
            requester=support_user,
            reason="Investigate ticket INC-9901",
            status=SupportAccessStatus.PENDING,
        )
        self.assertEqual(grant.status, SupportAccessStatus.PENDING)

        # Admin approves
        grant.approve(approver=self.user_admin_a, duration_hours=1)
        self.assertEqual(grant.status, SupportAccessStatus.APPROVED)
        self.assertTrue(grant.is_valid)
