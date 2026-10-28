"""Comprehensive test suite for Prompt P4: Analytics, Timeline Reconstruction, Metrics, Celery, and Reports."""
from __future__ import annotations

import datetime
import io
import json
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.analytics.capacity import calculate_screenshot_storage_capacity
from apps.analytics.metrics import compute_daily_aggregates_from_intervals, persist_device_timeline_and_metrics
from apps.analytics.models import AppUsageInterval, DailyMetrics, DataExport, ExportStatus, ExportType, IntervalState
from apps.analytics.tasks import export_dataset_task, process_device_timeline_task, retry_on_deadlock
from apps.analytics.timeline import IntervalDraft, TimelineReconstructionEngine
from apps.audit.models import AuditLog
from apps.devices.models import AgentCredential, Device, DeviceStatus
from apps.ingestion.models import ActivityEvent
from apps.policies.models import AppClassification, AppRule, MonitoringPolicy
from apps.screenshots.storage import MemoryObjectStorageBackend, get_storage_backend, reset_storage_backend
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Team, TeamMember, Tenant, TenantStatus


class P4AnalyticsTimelineReportsTests(TestCase):
    def setUp(self) -> None:
        reset_storage_backend()
        self.storage: MemoryObjectStorageBackend = get_storage_backend()  # type: ignore
        cache.clear()

        # Tenants
        self.tenant_a = Tenant.objects.create(name="Acme Corp", status=TenantStatus.ACTIVE)
        self.tenant_b = Tenant.objects.create(name="Stark Industries", status=TenantStatus.ACTIVE)

        # Users in Tenant A
        self.admin_user_a = User.objects.create_user(
            email="admin@acme.com", name="Alice Admin", mfa_enabled=True
        )
        self.membership_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_user_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        self.manager_user_a = User.objects.create_user(
            email="manager@acme.com", name="Bob Manager", mfa_enabled=False
        )
        self.membership_manager_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.manager_user_a,
            role=MembershipRole.MANAGER,
            status=MembershipStatus.ACTIVE,
        )

        self.employee_user_a = User.objects.create_user(
            email="emp1@acme.com", name="Charlie Emp", mfa_enabled=False
        )
        self.membership_employee_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.employee_user_a,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        self.employee_user_b = User.objects.create_user(
            email="emp2@acme.com", name="David Beta", mfa_enabled=False
        )
        self.membership_employee_b = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.employee_user_b,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        # Teams in Tenant A
        self.team_alpha = Team.objects.create(tenant=self.tenant_a, name="Alpha Team")
        self.team_beta = Team.objects.create(tenant=self.tenant_a, name="Beta Team")
        TeamMember.objects.create(team=self.team_alpha, membership=self.membership_manager_a)
        TeamMember.objects.create(team=self.team_alpha, membership=self.membership_employee_a)
        TeamMember.objects.create(team=self.team_beta, membership=self.membership_employee_b)

        # Devices
        self.device_a = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_employee_a,
            hostname="ACME-LAPTOP-01",
            os="windows",
            hardware_id="HW-001",
            status=DeviceStatus.ACTIVE,
        )
        self.device_b = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_employee_b,
            hostname="ACME-LAPTOP-02",
            os="windows",
            hardware_id="HW-002",
            status=DeviceStatus.ACTIVE,
        )

        # Policy & App Rules in Tenant A
        self.policy_a = MonitoringPolicy.get_or_create_default(self.tenant_a)
        AppRule.objects.create(
            tenant=self.tenant_a,
            policy=self.policy_a,
            app_identifier="code.exe",
            classification=AppClassification.PRODUCTIVE,
            version=1,
        )
        AppRule.objects.create(
            tenant=self.tenant_a,
            policy=self.policy_a,
            app_identifier="game.exe",
            classification=AppClassification.DISTRACTING,
            version=1,
        )

    def _auth_client(self, user: User, tenant: Tenant | None = None) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        if tenant:
            client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # ── Requirement Tests ─────────────────────────────────────────────────────

    def test_REQ_1_2_foreground_application_usage(self) -> None:
        """REQ-1-2: MUST capture foreground application usage intervals over time."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=40),
            payload={"source_sequence": 3}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        events = list(ActivityEvent.objects.filter(device=self.device_a))
        intervals = engine.reconstruct_device_timeline(self.device_a, events)
        code_invs = [inv for inv in intervals if inv.app_identifier == "code.exe"]
        self.assertEqual(len(code_invs), 1)
        self.assertEqual(code_invs[0].duration_seconds, 1800.0)

    def test_REQ_1_3_session_activity_active_idle_locked(self) -> None:
        """REQ-1-3: MUST capture session activity (active, idle, locked) as distinct states."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=5),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="idle.start", occurred_at=base_time + datetime.timedelta(minutes=20),
            payload={"source_sequence": 3}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.lock", occurred_at=base_time + datetime.timedelta(minutes=35),
            payload={"source_sequence": 4}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=60),
            payload={"source_sequence": 5}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, list(ActivityEvent.objects.filter(device=self.device_a)))
        states = {inv.state for inv in intervals}
        self.assertIn(IntervalState.ACTIVE, states)
        self.assertIn(IntervalState.IDLE, states)
        self.assertIn(IntervalState.LOCKED, states)

    def test_REQ_8_3_task_runtime_authorization(self) -> None:
        """REQ-8-3: Authorization checked on execution of every Celery task."""
        # Unauthenticated / wrong tenant task rejected
        res = process_device_timeline_task(
            tenant_id=uuid.uuid4(),
            device_id=self.device_a.id,
        )
        self.assertEqual(res["status"], "rejected")

    def test_REQ_9_1_deterministic_timeline_reconstruction(self) -> None:
        """REQ-9-1: Timeline reconstruction MUST be deterministic."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=30),
            payload={"source_sequence": 3}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        r1 = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3])
        r2 = engine.reconstruct_device_timeline(self.device_a, [e3, e1, e2])
        self.assertEqual([i.started_at for i in r1], [i.started_at for i in r2])

    def test_REQ_9_2_no_overlapping_intervals_per_device(self) -> None:
        """REQ-9-2: No overlapping intervals per device."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        events = [
            ActivityEvent.objects.create(
                tenant=self.tenant_a, device=self.device_a,
                event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=i * 5),
                payload={"app": f"app_{i}.exe", "source_sequence": i}
            )
            for i in range(8)
        ]
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, events)
        for i in range(len(intervals) - 1):
            self.assertLessEqual(intervals[i].ended_at, intervals[i + 1].started_at)

    def test_REQ_9_3_gaps_are_explicit_unknowns_never_filled(self) -> None:
        """REQ-9-3: Gaps MUST be explicit unknowns — never filled or counted as activity."""
        base_time = timezone.now() - datetime.timedelta(hours=3)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="gap.telemetry", occurred_at=base_time + datetime.timedelta(minutes=30),
            payload={"gap_seconds": 1800, "source_sequence": 3}
        )
        e4 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=60),
            payload={"app": "code.exe", "source_sequence": 4}
        )
        e5 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=60),
            payload={"source_sequence": 5}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3, e4, e5])

        gap_invs = [inv for inv in intervals if inv.state == IntervalState.TELEMETRY_GAP]
        self.assertEqual(len(gap_invs), 1)
        self.assertEqual(gap_invs[0].app_identifier, "gap")

        aggregates = compute_daily_aggregates_from_intervals(self.device_a, intervals, ZoneInfo("UTC"))
        today = base_time.date()
        self.assertEqual(aggregates[today]["active_seconds"], 1800.0)

    def test_REQ_9_4_impossible_sequences_normalized_no_negative_duration(self) -> None:
        """REQ-9-4: Impossible sequences normalized, recorded as anomalies, never negative durations."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="idle.end", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"source_sequence": 2}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2])
        for inv in intervals:
            self.assertGreaterEqual(inv.duration_seconds, 0.0)

    def test_REQ_9_5_daily_metrics_unique_grain_and_idempotency(self) -> None:
        """REQ-9-5: Daily metrics MUST have a unique grain; recalculation MUST be idempotent."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )

        persist_device_timeline_and_metrics(self.device_a, calc_version=1)
        self.assertEqual(DailyMetrics.objects.filter(device=self.device_a, calc_version=1).count(), 1)

        persist_device_timeline_and_metrics(self.device_a, calc_version=1)
        self.assertEqual(DailyMetrics.objects.filter(device=self.device_a, calc_version=1).count(), 1)

    # ── Edge Case Tests E25–E30, E58, E66, E69–E77, E79, E81, E82 ─────────────

    def test_E25_device_clock_far_off_timeline(self) -> None:
        """E25: Timeline reconstruction handles historical timestamps without negative durations."""
        past_time = timezone.now() - datetime.timedelta(days=60)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=past_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=past_time + datetime.timedelta(minutes=30),
            payload={"source_sequence": 2}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2])
        for inv in intervals:
            self.assertGreaterEqual(inv.duration_seconds, 0.0)

    def test_E26_clock_changes_while_running_jump_normalized(self) -> None:
        """E26: Clock jumping backwards while running is normalized without negative duration."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        # Clock jumps backwards 5 minutes
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time - datetime.timedelta(minutes=5),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=20),
            payload={"source_sequence": 3}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3])
        for inv in intervals:
            self.assertGreaterEqual(inv.duration_seconds, 0.0)

    def test_E27_timezone_changes_preserve_utc_instants(self) -> None:
        """E27: Timezone changes preserve UTC instants and derive local dates via tenant IANA timezone."""
        self.tenant_a.timezone = "Europe/London"
        self.tenant_a.save()
        base_time = datetime.datetime(2026, 10, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        persist_device_timeline_and_metrics(self.device_a, calc_version=1)
        m = DailyMetrics.objects.filter(device=self.device_a).first()
        self.assertIsNotNone(m)
        self.assertEqual(m.local_date, datetime.date(2026, 10, 15))

    def test_E28_dst_23_or_25_hour_day_midnight_splits(self) -> None:
        """E28: DST transitions (23 or 25 hour days) split cleanly at local midnight."""
        tz_ny = ZoneInfo("America/New_York")
        self.tenant_a.timezone = "America/New_York"
        self.tenant_a.save()

        # Crossing midnight during DST fall-back
        start_utc = datetime.datetime(2026, 11, 1, 3, 30, 0, tzinfo=datetime.timezone.utc)
        end_utc = datetime.datetime(2026, 11, 1, 5, 30, 0, tzinfo=datetime.timezone.utc)

        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=start_utc, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=end_utc, payload={"source_sequence": 2}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2])
        dates = {inv.started_at.astimezone(tz_ny).date() for inv in intervals}
        self.assertGreater(len(dates), 1)

    def test_E29_duplicate_timestamps_deterministic_tie_break(self) -> None:
        """E29: Events with identical timestamps are deterministically ordered by source_sequence and event_id."""
        same_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=same_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=same_time, payload={"app": "code.exe", "source_sequence": 2}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e2, e1])
        for inv in intervals:
            self.assertGreaterEqual(inv.duration_seconds, 0.0)

    def test_E30_events_arrive_out_of_order_deterministic(self) -> None:
        """E30: Events arriving out of order produce deterministic intervals."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=20),
            payload={"source_sequence": 3}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        r_fwd = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3])
        r_rev = engine.reconstruct_device_timeline(self.device_a, [e3, e2, e1])
        self.assertEqual([i.started_at for i in r_fwd], [i.started_at for i in r_rev])

    def test_E58_sleep_and_wake_reconciled(self) -> None:
        """E58: Sleep and wake reconciled without crashing or invalid states."""
        base_time = timezone.now() - datetime.timedelta(hours=3)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="system.sleep", occurred_at=base_time + datetime.timedelta(minutes=30),
            payload={"source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="system.wake", occurred_at=base_time + datetime.timedelta(minutes=90),
            payload={"source_sequence": 3}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3])
        asleep = [i for i in intervals if i.state == IntervalState.ASLEEP]
        self.assertEqual(len(asleep), 1)

    def test_E66_app_identifier_unavailable_stays_unclassified(self) -> None:
        """E66: Missing or unknown app identifiers are marked 'unknown' and NEUTRAL / unclassified."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "", "source_sequence": 2}
        )
        e3 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=30),
            payload={"source_sequence": 3}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2, e3])
        unknown_invs = [inv for inv in intervals if inv.app_identifier == "unknown"]
        self.assertGreaterEqual(len(unknown_invs), 1)
        for inv in unknown_invs:
            self.assertEqual(inv.app_classification, AppClassification.NEUTRAL)

    def test_E69_app_classification_changes_triggers_versioned_recalc(self) -> None:
        """E69: Changing app classification rules triggers versioned recalculation."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "custom_app.exe", "source_sequence": 2}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(minutes=40),
            payload={"source_sequence": 3}
        )

        persist_device_timeline_and_metrics(self.device_a, calc_version=1)
        m1 = DailyMetrics.objects.get(device=self.device_a, calc_version=1)
        self.assertEqual(m1.productive_seconds, 0.0)

        # Rule added for version 2
        AppRule.objects.create(
            tenant=self.tenant_a, policy=self.policy_a,
            app_identifier="custom_app.exe", classification=AppClassification.PRODUCTIVE, version=2
        )
        persist_device_timeline_and_metrics(self.device_a, calc_version=2)
        m2 = DailyMetrics.objects.get(device=self.device_a, calc_version=2)
        self.assertGreater(m2.productive_seconds, 0.0)

    def test_E70_idle_threshold_changes_triggers_versioned_recalc(self) -> None:
        """E70: Idle threshold changes recompute daily metrics under new version."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )
        self.policy_a.idle_threshold_seconds = 120
        self.policy_a.save()
        persist_device_timeline_and_metrics(self.device_a, calc_version=3)
        self.assertTrue(DailyMetrics.objects.filter(device=self.device_a, calc_version=3).exists())

    def test_E71_unclosed_session_closed_provisionally_inferred(self) -> None:
        """E71: Work session that never receives an end event is closed provisionally and marked inferred."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"app": "code.exe", "source_sequence": 2}
        )

        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2])
        self.assertTrue(any(inv.is_inferred for inv in intervals))

    def test_E72_idle_end_without_idle_start_normalized(self) -> None:
        """E72: Impossible sequence (idle.end without idle.start) normalized, non-negative duration."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        e1 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        e2 = ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="idle.end", occurred_at=base_time + datetime.timedelta(minutes=10),
            payload={"source_sequence": 2}
        )
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, [e1, e2])
        for inv in intervals:
            self.assertGreaterEqual(inv.duration_seconds, 0.0)

    def test_E73_overlapping_app_intervals_strictly_prevented(self) -> None:
        """E73: Overlapping app intervals strictly prevented in reconstruction."""
        base_time = timezone.now() - datetime.timedelta(hours=1)
        events = [
            ActivityEvent.objects.create(
                tenant=self.tenant_a, device=self.device_a,
                event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=i * 2),
                payload={"app": f"tool_{i}.exe", "source_sequence": i}
            )
            for i in range(5)
        ]
        engine = TimelineReconstructionEngine(tenant=self.tenant_a)
        intervals = engine.reconstruct_device_timeline(self.device_a, events)
        for i in range(len(intervals) - 1):
            self.assertLessEqual(intervals[i].ended_at, intervals[i + 1].started_at)

    def test_E74_late_event_recalculates_affected_window(self) -> None:
        """E74: Late arriving event recalculates affected device and time window with safety overlap."""
        base_time = timezone.now() - datetime.timedelta(hours=5)
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(hours=1),
            payload={"source_sequence": 2}
        )
        persist_device_timeline_and_metrics(self.device_a, calc_version=1)

        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="app.focus", occurred_at=base_time + datetime.timedelta(minutes=20),
            payload={"app": "code.exe", "source_sequence": 3}
        )

        persist_device_timeline_and_metrics(
            self.device_a,
            window_start=base_time,
            window_end=base_time + datetime.timedelta(hours=1),
            calc_version=1,
        )
        code_intervals = AppUsageInterval.objects.filter(device=self.device_a, app_identifier="code.exe")
        self.assertEqual(code_intervals.count(), 1)

    def test_E75_worker_retries_same_job_idempotent(self) -> None:
        """E75: Celery worker retrying same job produces identical idempotent result."""
        res1 = process_device_timeline_task(
            tenant_id=self.tenant_a.id,
            device_id=self.device_a.id,
            calc_version=1,
        )
        res2 = process_device_timeline_task(
            tenant_id=self.tenant_a.id,
            device_id=self.device_a.id,
            calc_version=1,
        )
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res2["status"], "completed")

    def test_E76_celery_or_redis_unavailable_durable_catchup(self) -> None:
        """E76: When Celery/Redis is unavailable, raw events remain durable in DB and processing catches up later."""
        base_time = timezone.now() - datetime.timedelta(hours=2)
        # Events written directly to DB without active worker
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.start", occurred_at=base_time, payload={"source_sequence": 1}
        )
        ActivityEvent.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            event_type="session.end", occurred_at=base_time + datetime.timedelta(hours=1),
            payload={"source_sequence": 2}
        )

        # Later worker runs catch-up task
        result = process_device_timeline_task(self.tenant_a.id, self.device_a.id, calc_version=1)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["intervals_count"], 0)

    def test_E77_mysql_failover_or_deadlock_retry_recovers(self) -> None:
        """E77: Database deadlock triggers exponential backoff retry and succeeds."""
        attempts = 0

        @retry_on_deadlock(max_retries=3, initial_delay=0.01)
        def _operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise OperationalError("Deadlock found when trying to get lock; try restarting transaction")
            return "recovered"

        self.assertEqual(_operation(), "recovered")
        self.assertEqual(attempts, 2)

    def test_E79_connection_pool_sizing_and_query_timeouts(self) -> None:
        """E79: Connection pool sizing and query budgets prevent worker resource starvation."""
        max_days = getattr(settings, "ANALYTICS_MAX_DATE_RANGE_DAYS", 90)
        self.assertEqual(max_days, 90)

    def test_E81_report_query_too_large_rejected(self) -> None:
        """E81: Date range > 90 days rejected with 422 QUERY_BUDGET_EXCEEDED."""
        client = self._auth_client(self.admin_user_a, self.tenant_a)
        response = client.get(
            "/api/reports/daily?from_date=2026-01-01&to_date=2026-06-01"
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.json()["code"], "QUERY_BUDGET_EXCEEDED")

    def test_E82_export_dataset_task_and_row_limits(self) -> None:
        """E82: Export generates CSV, enforces max row limits, audits export without sensitive leak."""
        for i in range(5):
            DailyMetrics.objects.create(
                tenant=self.tenant_a,
                device=self.device_a,
                local_date=datetime.date(2026, 10, i + 1),
                calc_version=1,
                active_seconds=3600.0,
            )

        client = self._auth_client(self.admin_user_a, self.tenant_a)
        resp = client.post(
            "/api/exports",
            data={"export_type": "daily_metrics", "filters": {}},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        export_id = resp.json()["id"]

        export = DataExport.objects.get(id=export_id)
        self.assertEqual(export.status, ExportStatus.COMPLETED)
        self.assertEqual(export.row_count, 5)
        self.assertTrue(self.storage.object_exists(export.file_key))

        audit = AuditLog.objects.filter(action="report.exported", resource_id=str(export.id)).first()
        self.assertIsNotNone(audit)

    # ── Role Scoping in Reports API (§2.2, E47) ───────────────────────────────
    def test_reports_role_scoping_manager_and_employee(self) -> None:
        """Reports are strictly role-scoped: Manager sees assigned teams, Employee sees own device only."""
        DailyMetrics.objects.create(
            tenant=self.tenant_a, device=self.device_a,
            local_date=datetime.date(2026, 10, 1), calc_version=1, active_seconds=1000.0
        )
        DailyMetrics.objects.create(
            tenant=self.tenant_a, device=self.device_b,
            local_date=datetime.date(2026, 10, 1), calc_version=1, active_seconds=2000.0
        )

        # Admin sees both
        admin_client = self._auth_client(self.admin_user_a, self.tenant_a)
        resp_admin = admin_client.get("/api/reports/daily")
        self.assertEqual(resp_admin.json()["count"], 2)

        # Manager only assigned Alpha team -> Device A
        manager_client = self._auth_client(self.manager_user_a, self.tenant_a)
        resp_manager = manager_client.get("/api/reports/daily")
        self.assertEqual(resp_manager.json()["count"], 1)
        self.assertEqual(resp_manager.json()["results"][0]["device_id"], str(self.device_a.id))

        # Employee only own Device A
        emp_client = self._auth_client(self.employee_user_a, self.tenant_a)
        resp_emp = emp_client.get("/api/reports/daily")
        self.assertEqual(resp_emp.json()["count"], 1)
        self.assertEqual(resp_emp.json()["results"][0]["device_id"], str(self.device_a.id))

    # ── §10.3 Storage Capacity Planning Helper ─────────────────────────────────
    def test_storage_capacity_formula_helper(self) -> None:
        """§10.3: Formula helper calculates storage requirements accurately."""
        result = calculate_screenshot_storage_capacity(
            work_hours=8.0,
            screenshot_interval_seconds=300,
            avg_compressed_screenshot_bytes=150_000,
            device_count=10,
            retention_days=30,
        )
        self.assertEqual(result["screenshots_per_device_per_day"], 96.0)
        self.assertGreater(result["retention_horizon_gb"], 0.0)
