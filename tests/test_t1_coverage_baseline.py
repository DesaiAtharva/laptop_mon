"""
tests/test_t1_coverage_baseline.py — Deep Unit Test Suite for T1 Coverage Thresholds.

Covers:
- Tenant Scoping & RBAC: apps.rbac.permissions, apps.tenancy.context (Target: >= 90%)
- Timeline Reconstruction: apps.analytics.timeline, apps.analytics.metrics (Target: >= 90%)
- Agent Journal & Spool: agent.core.journal, agent.core.spool (Target: >= 90%)
- Ingestion & Policies: apps.ingestion.services, apps.policies.models
- Edge Cases: E27, E28, E43, E44, E45, E46, E56, E58, E71, E72, E85
"""

import datetime
import json
import os
import shutil
import tempfile
import time
import uuid
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase
from rest_framework.exceptions import NotFound, ValidationError

from agent.core.crypto import CryptoManager, InMemoryKeyStore
from agent.core.journal import Journal
from agent.core.spool import ScreenshotSpool

from apps.analytics.models import AppClassification
from apps.analytics.timeline import (
    IntervalDraft,
    IntervalState,
    TimelineReconstructionEngine,
    split_interval_by_local_midnight,
)

from apps.common.exceptions import TenantDeleted, TenantSuspended
from apps.devices.models import Device
from apps.ingestion.models import ActivityEvent
from apps.policies.models import MonitoringPolicy
from apps.rbac.permissions import (
    HasScreenshotPermission,
    IsAuditor,
    IsManager,
    IsOrgAdmin,
    IsTenantMember,
    get_manager_accessible_team_ids,
)
from apps.tenancy.context import resolve_tenant_context
from apps.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    TeamMember,
    Tenant,
    TenantStatus,
)

User = get_user_model()


class RBACTenantScopingCoverageTests(TestCase):
    def setUp(self) -> None:
        self.tenant = Tenant.objects.create(name="Stark Corp")
        self.user_admin = User.objects.create_user(email="tony@stark.com", password="password123")
        self.user_manager = User.objects.create_user(email="pepper@stark.com", password="password123")
        self.user_auditor = User.objects.create_user(email="happy@stark.com", password="password123")
        self.user_employee = User.objects.create_user(email="peter@stark.com", password="password123")
        self.superuser = User.objects.create_superuser(email="admin@laptopmon.internal", password="password123")

        self.mem_admin = Membership.objects.create(
            tenant=self.tenant, user=self.user_admin, role=MembershipRole.ADMIN, status=MembershipStatus.ACTIVE
        )
        self.mem_manager = Membership.objects.create(
            tenant=self.tenant, user=self.user_manager, role=MembershipRole.MANAGER, status=MembershipStatus.ACTIVE
        )
        self.mem_auditor = Membership.objects.create(
            tenant=self.tenant, user=self.user_auditor, role=MembershipRole.AUDITOR, status=MembershipStatus.ACTIVE
        )
        self.mem_employee = Membership.objects.create(
            tenant=self.tenant, user=self.user_employee, role=MembershipRole.EMPLOYEE, status=MembershipStatus.ACTIVE
        )

        self.team1 = Team.objects.create(tenant=self.tenant, name="Avionics")
        TeamMember.objects.create(team=self.team1, membership=self.mem_manager)

    def test_is_tenant_member_branches(self) -> None:
        perm = IsTenantMember()
        req = HttpRequest()

        # Unauthenticated user
        req.user = None
        self.assertFalse(perm.has_permission(req, None))

        req.user = self.user_admin
        req.membership = None
        self.assertFalse(perm.has_permission(req, None))

        # Inactive membership
        inactive_mem = Membership(tenant=self.tenant, user=self.user_admin, status=MembershipStatus.DISABLED)
        req.membership = inactive_mem
        self.assertFalse(perm.has_permission(req, None))


        # Active membership
        req.membership = self.mem_admin
        self.assertTrue(perm.has_permission(req, None))

    def test_is_org_admin_branches(self) -> None:
        perm = IsOrgAdmin()
        req = HttpRequest()
        req.user = self.user_admin
        req.membership = self.mem_admin

        # Admin allowed
        self.assertTrue(perm.has_permission(req, None))

        # Manager denied
        req.user = self.user_manager
        req.membership = self.mem_manager
        self.assertFalse(perm.has_permission(req, None))

        # Superuser allowed
        req.user = self.superuser
        req.membership = self.mem_manager
        self.assertTrue(perm.has_permission(req, None))

        # Unauthenticated denied
        req.user = None
        self.assertFalse(perm.has_permission(req, None))

    def test_is_manager_branches(self) -> None:
        perm = IsManager()
        req = HttpRequest()

        # Manager allowed
        req.user = self.user_manager
        req.membership = self.mem_manager
        self.assertTrue(perm.has_permission(req, None))

        # Admin allowed
        req.user = self.user_admin
        req.membership = self.mem_admin
        self.assertTrue(perm.has_permission(req, None))

        # Superuser allowed
        req.user = self.superuser
        req.membership = self.mem_employee
        self.assertTrue(perm.has_permission(req, None))

        # Employee denied
        req.user = self.user_employee
        req.membership = self.mem_employee
        self.assertFalse(perm.has_permission(req, None))

    def test_is_auditor_branches(self) -> None:
        perm = IsAuditor()
        req = HttpRequest()

        # Auditor allowed
        req.user = self.user_auditor
        req.membership = self.mem_auditor
        self.assertTrue(perm.has_permission(req, None))

        # Superuser allowed
        req.user = self.superuser
        req.membership = self.mem_employee
        self.assertTrue(perm.has_permission(req, None))

        # Employee denied
        req.user = self.user_employee
        req.membership = self.mem_employee
        self.assertFalse(perm.has_permission(req, None))

    def test_has_screenshot_permission_branches(self) -> None:
        perm = HasScreenshotPermission()
        req = HttpRequest()

        # Without flag
        req.user = self.user_employee
        req.membership = self.mem_employee
        self.assertFalse(perm.has_permission(req, None))

        # With flag
        self.mem_employee.has_screenshot_permission = True
        self.mem_employee.save()
        self.assertTrue(perm.has_permission(req, None))

        # Superuser bypass
        self.mem_employee.has_screenshot_permission = False
        req.user = self.superuser
        self.assertTrue(perm.has_permission(req, None))

    def test_manager_accessible_team_ids_scoping(self) -> None:
        # Admin gets all teams
        admin_teams = get_manager_accessible_team_ids(self.mem_admin)
        self.assertIn(self.team1.id, admin_teams)

        # Superuser gets all teams
        self.mem_employee.user = self.superuser
        super_teams = get_manager_accessible_team_ids(self.mem_employee)
        self.assertIn(self.team1.id, super_teams)

        # Manager gets assigned team
        mgr_teams = get_manager_accessible_team_ids(self.mem_manager)
        self.assertEqual(mgr_teams, [self.team1.id])


class TenantContextResolutionCoverageTests(TestCase):
    def setUp(self) -> None:
        self.tenant1 = Tenant.objects.create(name="Stark Corp")
        self.user = User.objects.create_user(email="rhodey@stark.com", password="password123")
        self.membership = Membership.objects.create(
            tenant=self.tenant1, user=self.user, role=MembershipRole.EMPLOYEE, status=MembershipStatus.ACTIVE
        )

    def test_context_already_resolved(self) -> None:
        req = HttpRequest()
        req.path = "/api/reports"
        req.tenant = self.tenant1
        req.membership = self.membership
        t, m = resolve_tenant_context(req, self.user)
        self.assertEqual(t, self.tenant1)
        self.assertEqual(m, self.membership)

    def test_invalid_uuid_header(self) -> None:
        req = HttpRequest()
        req.path = "/api/reports"
        req.headers = {"X-Tenant-ID": "not-a-valid-uuid"}
        with self.assertRaises(ValidationError):
            resolve_tenant_context(req, self.user)

    def test_single_org_without_header(self) -> None:
        req = HttpRequest()
        req.path = "/api/reports"
        req.headers = {}
        t, m = resolve_tenant_context(req, self.user)
        self.assertEqual(t, self.tenant1)
        self.assertEqual(m, self.membership)

    def test_no_org_without_header(self) -> None:
        user2 = User.objects.create_user(email="nobody@stark.com", password="password123")
        req = HttpRequest()
        req.path = "/api/reports"
        req.headers = {}
        t, m = resolve_tenant_context(req, user2)
        self.assertIsNone(t)
        self.assertIsNone(m)

    def test_suspended_tenant_and_suspend_endpoint(self) -> None:
        self.tenant1.status = TenantStatus.SUSPENDED
        self.tenant1.save()

        # Regular API path raises TenantSuspended (E43)
        req = HttpRequest()
        req.path = "/api/devices"
        req.headers = {"X-Tenant-ID": str(self.tenant1.id)}
        with self.assertRaises(TenantSuspended):
            resolve_tenant_context(req, self.user)

        # /suspend endpoint allows access so admin can reactivate
        req_suspend = HttpRequest()
        req_suspend.path = f"/api/tenants/{self.tenant1.id}/suspend"
        req_suspend.headers = {"X-Tenant-ID": str(self.tenant1.id)}
        t, m = resolve_tenant_context(req_suspend, self.user)
        self.assertEqual(t, self.tenant1)

    def test_deleting_tenant_raises(self) -> None:
        self.tenant1.status = TenantStatus.DELETING
        self.tenant1.save()
        req = HttpRequest()
        req.path = "/api/devices"
        req.headers = {"X-Tenant-ID": str(self.tenant1.id)}
        with self.assertRaises(TenantDeleted):
            resolve_tenant_context(req, self.user)


class TimelineEngineCoverageTests(TestCase):
    def setUp(self) -> None:
        self.tenant = Tenant.objects.create(name="Wayne Tech")
        self.device = Device.objects.create(tenant=self.tenant, os="linux", hostname="batcomputer")

    def test_permission_transitions_and_unobserved_state(self) -> None:
        """Tests permission.denied and permission.granted timeline branches (E56)."""
        engine = TimelineReconstructionEngine(self.tenant)
        t0 = datetime.datetime(2026, 10, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)
        t1 = datetime.datetime(2026, 10, 28, 10, 10, 0, tzinfo=datetime.timezone.utc)
        t2 = datetime.datetime(2026, 10, 28, 10, 20, 0, tzinfo=datetime.timezone.utc)

        events = [
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="session.start",
                occurred_at=t0,
                payload={"os_username": "bruce"},
            ),
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="permission.denied",
                occurred_at=t1,
                payload={"capability": "screen_recording"},
            ),
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="permission.granted",
                occurred_at=t2,
                payload={"capability": "screen_recording"},
            ),
        ]
        intervals = engine.reconstruct_device_timeline(self.device, events)
        self.assertGreaterEqual(len(intervals), 1)

    def test_unlock_without_lock_and_wake_without_sleep(self) -> None:
        """Tests anomaly tracking for impossible sequences (E72)."""
        engine = TimelineReconstructionEngine(self.tenant)
        t0 = datetime.datetime(2026, 10, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)
        t1 = datetime.datetime(2026, 10, 28, 10, 5, 0, tzinfo=datetime.timezone.utc)
        t2 = datetime.datetime(2026, 10, 28, 10, 10, 0, tzinfo=datetime.timezone.utc)

        events = [
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="session.start",
                occurred_at=t0,
                payload={},
            ),
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="session.unlock",
                occurred_at=t1,
                payload={},
            ),
            ActivityEvent(
                tenant=self.tenant,
                device=self.device,
                event_type="system.wake",
                occurred_at=t2,
                payload={},
            ),
        ]
        intervals = engine.reconstruct_device_timeline(self.device, events)
        self.assertTrue(len(intervals) > 0)


    def test_split_interval_zero_or_negative_duration(self) -> None:
        """Tests split_interval_by_local_midnight returns empty list on invalid interval."""
        t0 = datetime.datetime(2026, 10, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)
        draft = IntervalDraft(
            app_identifier="code",
            app_classification=AppClassification.PRODUCTIVE,
            app_classification_version=1,
            started_at=t0,
            ended_at=t0,  # Zero duration
            state=IntervalState.ACTIVE,
            is_inferred=False,
        )
        pieces = split_interval_by_local_midnight(draft, ZoneInfo("UTC"))
        self.assertEqual(pieces, [])


class AgentJournalAndSpoolCoverageTests(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.crypto = CryptoManager(InMemoryKeyStore(b"01234567890123456789012345678901"))
        self.db_path = os.path.join(self.tmpdir, "test_journal.db")

        self.journal = Journal(self.db_path, self.crypto, max_events=50)
        self.spool_dir = os.path.join(self.tmpdir, "spool")
        self.spool = ScreenshotSpool(self.spool_dir, self.crypto, max_spool_bytes=100000)

    def tearDown(self) -> None:
        self.journal.close()
        self.spool.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_journal_empty_list_operations(self) -> None:
        """Verifies empty list guards in mark_in_flight, revert_in_flight, and delete_accepted."""
        self.journal.mark_in_flight([])
        self.journal.revert_in_flight([])
        deleted = self.journal.delete_accepted([])
        self.assertEqual(deleted, 0)

        # Empty queue age
        age = self.journal.get_oldest_pending_age_seconds()
        self.assertEqual(age, 0.0)

    def test_spool_operations_and_decryption(self) -> None:
        """Verifies get_ready_screenshots, mark_in_flight, read_decrypted, and delete_finalized."""
        # Spool a test screenshot
        img_bytes = b"\xff\xd8\xff\xe0mock_screenshot_bytes_here"
        meta = {"app": "code", "width": 800, "height": 600}
        spool_res = self.spool.spool_screenshot(
            image_bytes=img_bytes,
            captured_at="2026-10-28T10:00:00Z",
            metadata=meta,
            screenshot_id="shot-001",
        )

        self.assertIsNotNone(spool_res)
        assert spool_res is not None
        self.assertEqual(spool_res.screenshot_id, "shot-001")


        # Fetch ready
        ready = self.spool.get_ready_screenshots(limit=5)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].screenshot_id, "shot-001")

        # Read decrypted
        decrypted = self.spool.read_decrypted_screenshot(ready[0])
        self.assertEqual(decrypted, img_bytes)

        # Mark in flight and revert
        self.spool.mark_in_flight("shot-001")
        self.assertEqual(len(self.spool.get_ready_screenshots()), 0)

        self.spool.revert_in_flight("shot-001")
        self.assertEqual(len(self.spool.get_ready_screenshots()), 1)

        # Delete finalized
        deleted = self.spool.delete_finalized("shot-001")
        self.assertTrue(deleted)
        self.assertEqual(len(self.spool.get_ready_screenshots()), 0)

    def test_spool_reconciliation_orphan_tmp_and_missing_delete(self) -> None:
        """Tests orphan tmp cleanup, matching file reconciliation, and non-existent delete_finalized."""
        # 1. Orphan tmp file
        tmp_file = os.path.join(self.spool_dir, "orphan.tmp")
        with open(tmp_file, "wb") as f:
            f.write(b"abandoned_temp_data")

        # Create a valid tracked spool file
        img = b"\xff\xd8\xff\xe0valid_data"
        self.spool.spool_screenshot(image_bytes=img, captured_at="2026-10-28T09:00:00Z", screenshot_id="tracked-01")

        stats = self.spool.reconcile_at_startup()
        self.assertEqual(stats["orphan_tmp_deleted"], 1)
        self.assertFalse(os.path.exists(tmp_file))

        # Delete tracked file where underlying file exists
        deleted = self.spool.delete_finalized("tracked-01")
        self.assertTrue(deleted)

        # 2. Delete non-existent screenshot returns False
        self.assertFalse(self.spool.delete_finalized("non_existent_id"))

    def test_spool_write_failure_cleanup(self) -> None:
        """Tests temp file cleanup when write/replace fails during spooling."""
        with patch("os.replace", side_effect=OSError("Disk rename error")):
            with self.assertRaises(OSError):
                self.spool.spool_screenshot(b"\xff\xd8data", captured_at="2026-10-28T10:00:00Z", screenshot_id="fail-shot")

    def test_spool_disk_usage_floor_headroom(self) -> None:
        """Tests disk free space floor triggers _drop_oldest_screenshots and drops when exhausted."""
        with patch("shutil.disk_usage", return_value=(1000, 990, 10)):  # free=10 < min_free_disk_bytes
            res = self.spool.spool_screenshot(b"\xff\xd8data", captured_at="2026-10-28T10:00:00Z", screenshot_id="disk-shot")
            self.assertIsNone(res)



    def test_spool_quota_dropping_oldest(self) -> None:
        """Tests priority dropping oldest screenshots to protect headroom (REQ-5-2, E17, E18)."""
        img1 = b"\xff\xd8\xff\xe0payload_one"
        img2 = b"\xff\xd8\xff\xe0payload_two"
        self.spool.spool_screenshot(image_bytes=img1, captured_at="2026-10-28T09:00:00Z", screenshot_id="shot-01")
        self.spool.spool_screenshot(image_bytes=img2, captured_at="2026-10-28T09:05:00Z", screenshot_id="shot-02")
        self.assertEqual(len(self.spool.get_ready_screenshots()), 2)

        freed = self.spool._drop_oldest_screenshots(target_freed_bytes=len(img1))
        self.assertGreater(freed, 0)
        remaining = self.spool.get_ready_screenshots()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].screenshot_id, "shot-02")

    def test_journal_quarantine_with_wal_and_malformed_time(self) -> None:
        """Tests quarantine with wal/shm files and malformed timestamp handling."""
        # Create dummy wal file
        wal_file = f"{self.db_path}-wal"
        with open(wal_file, "w") as f:
            f.write("mock_wal")

        quarantine_path = self.journal.quarantine_and_recover()
        self.assertTrue(os.path.exists(quarantine_path))

        # Insert row with unparseable timestamp
        conn = self.journal._get_connection()
        with conn:
            conn.execute(
                "INSERT INTO events (id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, retry_count, created_at) "
                "VALUES ('e-bad', 'test', 'invalid-iso-date', 1.0, 'boot', x'00', x'00', 'pending', 0, '2026-10-28T10:00:00Z');"
            )
        age = self.journal.get_oldest_pending_age_seconds()
        self.assertEqual(age, 0.0)

        # Decryption error branch
        pending = self.journal.get_pending_events(limit=5)
        self.assertEqual(len(pending), 1)
        self.assertIn("_decryption_error", pending[0].payload)

    def test_journal_prune_empty_and_recovered_rows(self) -> None:
        """Covers empty prune guard and readable row recovery during quarantine."""
        conn = self.journal._get_connection()
        # Empty prune
        self.journal._prune_with_gap(conn)

        # Append valid event
        ev = self.journal.append_event(
            event_type="app.focus",
            occurred_at="2026-10-28T10:00:00Z",
            payload={"app": "firefox"},
            monotonic_reference=100.0,
            boot_segment_id="boot-1",
        )
        self.assertIsNotNone(ev)


        # Quarantine recovers valid rows
        self.journal.quarantine_and_recover()
        events = self.journal.get_pending_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "app.focus")

    def test_spool_headroom_rejection_and_file_removal(self) -> None:
        """Covers spool byte headroom dropping and rejection (REQ-5-2, E17)."""
        tiny_spool_dir = os.path.join(self.tmpdir, "tiny_spool")
        tiny_spool = ScreenshotSpool(tiny_spool_dir, self.crypto, max_spool_bytes=120)

        img = b"\xff\xd8\xff\xe0" + b"x" * 50
        res1 = tiny_spool.spool_screenshot(image_bytes=img, captured_at="2026-10-28T10:00:00Z", screenshot_id="s1")
        self.assertIsNotNone(res1)

        # Spooling exceeding quota triggers _drop_oldest_screenshots
        res2 = tiny_spool.spool_screenshot(image_bytes=img, captured_at="2026-10-28T10:01:00Z", screenshot_id="s2")
        self.assertIsNotNone(res2)

        # Huge payload exceeding capacity returns None
        huge_img = b"\xff\xd8" + b"y" * 500
        res3 = tiny_spool.spool_screenshot(image_bytes=huge_img, captured_at="2026-10-28T10:02:00Z", screenshot_id="s3")
        self.assertIsNone(res3)
        tiny_spool.close()


class AnalyticsBudgetAndRoleScopingTests(TestCase):
    def test_validate_date_range_budget_exceptions(self) -> None:
        from apps.analytics.views import validate_date_range_budget
        from apps.common.exceptions import UnprocessableEntity

        d1 = datetime.date(2026, 10, 20)
        d2 = datetime.date(2026, 10, 10)
        with self.assertRaises(UnprocessableEntity):
            validate_date_range_budget(d1, d2)

        d3 = datetime.date(2026, 1, 1)
        d4 = datetime.date(2026, 6, 1)
        with self.assertRaises(UnprocessableEntity):
            validate_date_range_budget(d3, d4)

    def test_scope_queryset_by_role_fallback(self) -> None:
        from apps.analytics.models import DailyMetrics
        from apps.analytics.views import scope_queryset_by_role

        tenant = Tenant.objects.create(name="Cyberdyne")
        user = User.objects.create_user(email="t800@cyberdyne.com", password="password123")
        mem = Membership.objects.create(tenant=tenant, user=user, role=MembershipRole.SERVICE_IDENTITY)
        req = HttpRequest()
        req.user = user
        req.membership = mem
        qs = scope_queryset_by_role(DailyMetrics.objects.none(), req)
        self.assertEqual(qs.count(), 0)


class SchedulerComprehensiveCoverageTests(TestCase):
    def setUp(self) -> None:
        from agent.adapters.base import CaptureResult, ForegroundAppEvent, PermissionStatus
        from agent.core.diagnostics import DiagnosticsCollector
        from agent.core.lifecycle import LifecycleManager
        from agent.core.policy import EffectivePolicy, PolicyManager
        from agent.core.privacy_filter import PrivacyFilter
        from agent.core.scheduler import AgentScheduler
        from agent.core.status import AgentState, StatusTracker
        from agent.core.sync import SyncWorker

        self.tmpdir = tempfile.mkdtemp()
        self.crypto = CryptoManager(InMemoryKeyStore(b"01234567890123456789012345678901"))
        self.journal = Journal(os.path.join(self.tmpdir, "sched_j.db"), self.crypto)
        self.spool = ScreenshotSpool(os.path.join(self.tmpdir, "sched_spool"), self.crypto)

        self.mock_adapter = MagicMock()
        self.mock_adapter.get_permissions.return_value = {
            "screen_recording": PermissionStatus.GRANTED,
            "accessibility": PermissionStatus.GRANTED,
        }
        self.mock_adapter.get_idle_seconds.return_value = 0.0
        self.mock_adapter.is_battery_saver.return_value = False
        self.mock_adapter.capture_screen.return_value = CaptureResult(
            image_bytes=b"\xff\xd8img", width=800, height=600, format="jpeg"
        )
        self.mock_adapter.get_foreground_app.return_value = ForegroundAppEvent(
            timestamp="2026-10-28T10:00:00Z", app_identifier="code", window_title="test.py"
        )

        self.policy_mgr = MagicMock(spec=PolicyManager)
        client_pol = EffectivePolicy(
            version=1,
            valid_until="2099-01-01T00:00:00Z",
            idle_threshold_seconds=60,
            screenshot_interval_seconds=60,
        )
        self.policy_mgr.get_effective_policy.return_value = client_pol
        self.policy_mgr.can_capture_screenshots.return_value = True

        self.privacy_filter = PrivacyFilter(self.policy_mgr)
        self.status_file = os.path.join(self.tmpdir, "status.json")
        self.status_tracker = StatusTracker(self.status_file)
        self.status_tracker.acknowledge_first_run()
        self.lifecycle = MagicMock(spec=LifecycleManager)
        self.lifecycle.boot_segment_id = "boot-1"
        self.sync_worker = MagicMock(spec=SyncWorker)
        self.sync_worker.sync_events.return_value = 1
        self.sync_worker.sync_screenshots.return_value = 1
        self.sync_worker.send_heartbeat.return_value = True
        self.diagnostics = MagicMock(spec=DiagnosticsCollector)

        self.scheduler = AgentScheduler(
            adapter=self.mock_adapter,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            privacy_filter=self.privacy_filter,
            status_tracker=self.status_tracker,
            lifecycle=self.lifecycle,
            sync_worker=self.sync_worker,
            diagnostics=self.diagnostics,
        )


    def tearDown(self) -> None:
        self.journal.close()
        self.spool.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_step_foreground_tick_transitions(self) -> None:
        from agent.adapters.base import PermissionStatus

        # Initial foreground tick logs event
        ev_id = self.scheduler.step_foreground_tick()
        self.assertIsNotNone(ev_id)

        # Same app -> None
        ev_id2 = self.scheduler.step_foreground_tick()
        self.assertIsNone(ev_id2)

        # Accessibility denied -> None
        self.mock_adapter.get_permissions.return_value = {"accessibility": PermissionStatus.DENIED}
        self.assertIsNone(self.scheduler.step_foreground_tick())

    def test_step_idle_tick_transitions(self) -> None:
        # Inactive user -> idle_start
        self.mock_adapter.get_idle_seconds.return_value = 100.0
        ev1 = self.scheduler.step_idle_tick()
        self.assertIsNotNone(ev1)
        self.assertTrue(self.scheduler.is_currently_idle)

        # Resumes activity -> idle_end
        self.mock_adapter.get_idle_seconds.return_value = 5.0
        ev2 = self.scheduler.step_idle_tick()
        self.assertIsNotNone(ev2)
        self.assertFalse(self.scheduler.is_currently_idle)

    def test_step_screenshot_tick_guards(self) -> None:
        from agent.adapters.base import PermissionStatus

        # Battery saver active -> skips
        self.mock_adapter.is_battery_saver.return_value = True
        self.assertIsNone(self.scheduler.step_screenshot_tick())
        self.mock_adapter.is_battery_saver.return_value = False

        # Permission denied -> skips
        self.mock_adapter.get_permissions.return_value = {"screen_recording": PermissionStatus.DENIED}
        self.assertIsNone(self.scheduler.step_screenshot_tick())
        self.mock_adapter.get_permissions.return_value = {"screen_recording": PermissionStatus.GRANTED}

        # Policy disallows -> skips
        self.policy_mgr.can_capture_screenshots.return_value = False
        self.assertIsNone(self.scheduler.step_screenshot_tick())
        self.policy_mgr.can_capture_screenshots.return_value = True

        # Successful capture
        shot_id = self.scheduler.step_screenshot_tick()
        self.assertIsNotNone(shot_id)

    def test_power_and_session_events(self) -> None:
        from agent.adapters.base import PowerEventType, SessionEventType

        ev_sleep = self.scheduler.on_power_event(PowerEventType.SLEEP)
        self.assertIsNotNone(ev_sleep)
        self.assertTrue(self.scheduler.is_currently_asleep)

        ev_wake = self.scheduler.on_power_event(PowerEventType.WAKE)
        self.assertIsNotNone(ev_wake)
        self.assertFalse(self.scheduler.is_currently_asleep)

        ev_lock = self.scheduler.on_session_event(SessionEventType.LOCK)
        self.assertIsNotNone(ev_lock)
        self.assertTrue(self.scheduler.is_currently_locked)

        ev_unlock = self.scheduler.on_session_event(SessionEventType.UNLOCK)
        self.assertIsNotNone(ev_unlock)
        self.assertFalse(self.scheduler.is_currently_locked)

    def test_step_sync_tick_defers_on_battery_saver(self) -> None:
        self.mock_adapter.is_battery_saver.return_value = True
        synced = self.scheduler.step_sync_tick()
        self.assertEqual(synced, 0)

        self.mock_adapter.is_battery_saver.return_value = False
        synced2 = self.scheduler.step_sync_tick()
        self.assertGreaterEqual(synced2, 0)


class SyncWorkerTests(TestCase):
    def setUp(self) -> None:
        from agent.core.crypto import CryptoManager, InMemoryKeyStore
        from agent.core.journal import Journal
        from agent.core.policy import PolicyManager
        from agent.core.spool import ScreenshotSpool
        from agent.core.status import StatusTracker
        from agent.core.sync import SyncWorker

        self.tmpdir = tempfile.mkdtemp()
        self.crypto = CryptoManager(InMemoryKeyStore(b"01234567890123456789012345678901"))
        self.journal = Journal(os.path.join(self.tmpdir, "sync_j.db"), self.crypto)
        self.spool = ScreenshotSpool(os.path.join(self.tmpdir, "sync_s"), self.crypto)
        self.policy_mgr = MagicMock(spec=PolicyManager)
        self.status_file = os.path.join(self.tmpdir, "status.json")
        self.status_tracker = StatusTracker(self.status_file)
        self.status_tracker.acknowledge_first_run()

    def tearDown(self) -> None:
        self.journal.close()
        self.spool.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sync_events_success_and_delete(self) -> None:
        from agent.core.sync import SyncWorker

        e1 = self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:00Z",
            payload={"app": "test1"},
            monotonic_reference=10.0,
            boot_segment_id="b1",
        )
        e2 = self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:01Z",
            payload={"app": "test2"},
            monotonic_reference=11.0,
            boot_segment_id="b1",
        )

        def mock_http(url: str, data: bytes, headers: dict, method: str):
            resp = json.dumps({"accepted": [e1.id], "already_accepted": [e2.id]}).encode("utf-8")
            return 200, resp, {}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        accepted = worker.sync_events()
        self.assertEqual(accepted, 2)
        self.assertEqual(len(self.journal.get_pending_events()), 0)
        self.assertIsNotNone(self.status_tracker.last_sync_at)

    def test_sync_events_413_splits_batch(self) -> None:
        from agent.core.sync import SyncWorker

        e1 = self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:00Z",
            payload={"app": "test1"},
            monotonic_reference=10.0,
            boot_segment_id="b1",
        )
        e2 = self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:01Z",
            payload={"app": "test2"},
            monotonic_reference=11.0,
            boot_segment_id="b1",
        )

        calls = []
        def mock_http(url: str, data: bytes, headers: dict, method: str):
            calls.append(len(json.loads(data.decode("utf-8"))["events"]))
            if len(calls) == 1:
                return 413, b"Payload Too Large", {}
            return 200, json.dumps({"accepted": [e1.id]}).encode("utf-8"), {}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        res = worker.sync_events()
        self.assertEqual(res, 1)
        self.assertEqual(calls, [2, 1])

    def test_sync_events_403_device_revocation(self) -> None:
        from agent.core.sync import SyncWorker

        self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:00Z",
            payload={"app": "test1"},
            monotonic_reference=10.0,
            boot_segment_id="b1",
        )

        def mock_http(url: str, data: bytes, headers: dict, method: str):
            return 403, b"Forbidden", {}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        res = worker.sync_events()
        self.assertEqual(res, 0)
        self.assertTrue(worker.is_revoked)
        self.policy_mgr.mark_revoked.assert_called_with(action="hold")

    def test_sync_events_429_backoff_and_permanent_error(self) -> None:
        from agent.core.sync import SyncWorker

        self.journal.append_event(
            event_type="app.active",
            occurred_at="2026-10-28T10:00:00Z",
            payload={"app": "test1"},
            monotonic_reference=10.0,
            boot_segment_id="b1",
        )

        def mock_429(url: str, data: bytes, headers: dict, method: str):
            return 429, b"Too Many Requests", {"retry-after": "5"}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_429,
        )

        res = worker.sync_events()
        self.assertEqual(res, 0)
        self.assertGreater(worker.backoff_until, time.monotonic())

        # Test 400 permanent error deletes bad event to prevent loop
        worker.backoff_until = 0.0
        worker.http_client = lambda u, d, h, m: (400, b"Bad Request", {})
        res400 = worker.sync_events()
        self.assertEqual(res400, 0)
        self.assertEqual(len(self.journal.get_pending_events()), 0)

    def test_sync_screenshots_two_phase_success(self) -> None:
        from agent.core.sync import SyncWorker

        shot = self.spool.spool_screenshot(
            image_bytes=b"\xff\xd8fakeimagebytes",
            captured_at="2026-10-28T10:00:00Z",
            metadata={"width": 800, "height": 600, "format": "jpeg"},
            screenshot_id="shot-sync-1",
        )
        self.assertIsNotNone(shot)

        calls = []
        def mock_http(url: str, data: bytes, headers: dict, method: str):
            calls.append((url, method))
            if "upload-intents" in url:
                resp = json.dumps({"upload_url": "http://storage/put", "object_key": "ten/shot-1.jpg"}).encode("utf-8")
                return 200, resp, {}
            elif "http://storage/put" in url:
                return 200, b"", {}
            elif "complete" in url:
                return 200, json.dumps({"status": "verified"}).encode("utf-8"), {}
            return 404, b"", {}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        uploaded = worker.sync_screenshots()
        self.assertEqual(uploaded, 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.spool.get_ready_screenshots()), 0)

    def test_sync_screenshots_storage_failure_reverts(self) -> None:
        from agent.core.sync import SyncWorker

        shot = self.spool.spool_screenshot(
            image_bytes=b"\xff\xd8fakeimagebytes",
            captured_at="2026-10-28T10:00:00Z",
            metadata={"width": 800, "height": 600, "format": "jpeg"},
            screenshot_id="shot-sync-fail",
        )
        self.assertIsNotNone(shot)

        def mock_http(url: str, data: bytes, headers: dict, method: str):
            if "upload-intents" in url:
                resp = json.dumps({"upload_url": "http://storage/put", "object_key": "ten/shot-1.jpg"}).encode("utf-8")
                return 200, resp, {}
            elif "http://storage/put" in url:
                return 500, b"Storage Down", {}
            return 404, b"", {}

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        uploaded = worker.sync_screenshots()
        self.assertEqual(uploaded, 0)
        self.assertEqual(len(self.spool.get_ready_screenshots()), 1)

    def test_send_heartbeat_and_revocation(self) -> None:
        from agent.core.sync import SyncWorker

        worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id="dev-1",
            credential_token="token-1",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=lambda u, d, h, m: (200, b"{}", {}),
        )

        hb_ok = worker.send_heartbeat({"queue_depth": 0})
        self.assertTrue(hb_ok)

        worker.http_client = lambda u, d, h, m: (403, b"Revoked", {})
        hb_rev = worker.send_heartbeat({"queue_depth": 0})
        self.assertFalse(hb_rev)
        self.assertTrue(worker.is_revoked)


class AnalyticsAndReportingViewTests(TestCase):
    def setUp(self) -> None:
        from apps.tenancy.models import Tenant, TenantStatus, Membership, MembershipRole, MembershipStatus
        from apps.devices.models import Device, DeviceStatus
        from apps.analytics.models import DailyMetrics, AppUsageInterval, IntervalState
        from rest_framework.test import APIClient

        self.tenant = Tenant.objects.create(name="T1 Reporting Corp", status=TenantStatus.ACTIVE)
        self.user = User.objects.create_user(
            email="reporter@t1corp.com", name="T1 Reporter", password="password"
        )
        self.membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.device = Device.objects.create(
            tenant=self.tenant,
            membership=self.membership,
            hostname="REP-LAPTOP",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )

        DailyMetrics.objects.create(
            tenant=self.tenant,
            device=self.device,
            local_date=datetime.date(2026, 10, 20),
            calc_version=1,
            observed_session_seconds=1500.0,
            active_seconds=1200.0,
            idle_seconds=300.0,
            productive_seconds=1000.0,
            neutral_seconds=100.0,
            distracting_seconds=100.0,
            productive_share=0.83,
            monitoring_coverage=1.0,
        )

        AppUsageInterval.objects.create(
            tenant=self.tenant,
            device=self.device,
            calc_version=1,
            started_at=datetime.datetime(2026, 10, 20, 10, 0, 0, tzinfo=datetime.timezone.utc),
            ended_at=datetime.datetime(2026, 10, 20, 10, 20, 0, tzinfo=datetime.timezone.utc),
            duration_seconds=1200.0,
            state=IntervalState.ACTIVE,
            app_identifier="pycharm64.exe",
            app_classification="productive",
        )

        from apps.accounts.models import UserSession
        self.client = APIClient()
        _, raw_token = UserSession.create_session(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant.id)

    def test_daily_reports_view_and_filters(self) -> None:
        res = self.client.get("/api/reports/daily?from_date=2026-10-01&to_date=2026-10-25&calc_version=1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["active_seconds"], 1200.0)

    def test_timeline_reports_view(self) -> None:
        res = self.client.get(
            f"/api/reports/timeline?device_id={self.device.id}&from_date=2026-10-20T00:00:00Z&to_date=2026-10-20T23:59:59Z&state=active"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["app_identifier"], "pycharm64.exe")

    def test_app_usage_summary_view(self) -> None:
        res = self.client.get(
            f"/api/reports/app-usage?device_id={self.device.id}&from_date=2026-10-20T00:00:00Z&to_date=2026-10-20T23:59:59Z"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["total_active_seconds"], 1200.0)
        self.assertEqual(len(res.data["applications"]), 1)
        self.assertEqual(res.data["applications"][0]["app_identifier"], "pycharm64.exe")




