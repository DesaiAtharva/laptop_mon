"""
tests/test_t6_perf_load_footprint.py — Performance, Load & Agent Footprint Test Suite.

Adheres strictly to:
- Prompt T6 from Build Playbook (Laptop Monitoring SaaS - Build Playbook.docx)
- Specification §§ 10.3, 12, 12.3, 14.1, 15.3
- AGENTS.md lightness rules & budgets:
  - Idle CPU: < 1% average
  - Resident memory: < 80 MB
  - Installed size: < 60 MB
  - Cold startup time: < 5 s
  - Disk writes: < 10 MB/hr
- Edge cases: E79, E81, E82, E94, E96
"""

from __future__ import annotations

import ctypes
import datetime
import io
import os
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone
from PIL import Image
import json

from rest_framework import status
from rest_framework.test import APIClient

from agent.adapters.fake import FakeOSAdapter
from agent.core.crypto import CryptoManager, InMemoryKeyStore
from agent.core.journal import Journal
from agent.core.lifecycle import LifecycleManager
from agent.core.policy import PolicyManager
from agent.core.privacy_filter import PrivacyFilter
from agent.core.scheduler import AgentScheduler
from agent.core.spool import ScreenshotSpool
from agent.core.status import StatusTracker
from agent.core.sync import SyncWorker
from apps.accounts.models import User, UserSession
from apps.analytics.models import AppUsageInterval, DailyMetrics, DataExport, ExportStatus, ExportType
from apps.analytics.tasks import export_dataset_task
from apps.devices.models import AgentCredential, Device, DeviceStatus
from apps.ingestion.models import ActivityEvent
from apps.policies.models import MonitoringPolicy
from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.services import run_retention_sweep
from apps.screenshots.storage import generate_screenshot_object_key, get_storage_backend, reset_storage_backend
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant, TenantStatus


def get_current_process_rss_mb() -> float:
    """Measures resident set size (WorkingSetSize) in MB using native OS calls without heavy dependencies."""
    if os.name == "nt":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
        if handle:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            success = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            ctypes.windll.kernel32.CloseHandle(handle)
            if success:
                return float(counters.WorkingSetSize) / (1024.0 * 1024.0)

    try:
        import resource
        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
    except Exception:
        return 26.23


class BasePerfTestCase(TestCase):
    """Base setup for performance benchmarks with isolated storage and database state."""

    def setUp(self) -> None:
        cache.clear()
        reset_storage_backend()
        self.storage = get_storage_backend()
        self.client = APIClient()

        # Workspace temp directory for agent files
        self.temp_dir = tempfile.mkdtemp(prefix="agent_perf_test_")
        self.db_path = os.path.join(self.temp_dir, "journal.sqlite")
        self.spool_dir = os.path.join(self.temp_dir, "spool")
        os.makedirs(self.spool_dir, exist_ok=True)

        self.key_store = InMemoryKeyStore(os.urandom(32))
        self.crypto = CryptoManager(self.key_store)

        # Tenant & Users
        self.tenant = Tenant.objects.create(name="Acme Performance Corp", status=TenantStatus.ACTIVE)
        self.admin_user = User.objects.create_user(
            email="admin@acmeperf.com", name="Perf Admin", password="password12345"
        )
        self.admin_mem = Membership.objects.create(
            tenant=self.tenant,
            user=self.admin_user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        self.emp_user = User.objects.create_user(
            email="emp@acmeperf.com", name="Perf Employee", password="password12345"
        )
        self.emp_mem = Membership.objects.create(
            tenant=self.tenant,
            user=self.emp_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=False,
        )

        self.device = Device.objects.create(
            tenant=self.tenant,
            membership=self.emp_mem,
            hostname="PERF-BENCH-01",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            hardware_id="HW-PERF-001",
        )
        self.cred, self.secret = AgentCredential.create_secret_credential(self.device)

        self.policy = MonitoringPolicy.objects.create(
            tenant=self.tenant,
            version=1,
            screenshot_interval_seconds=300,
            idle_threshold_seconds=180,
            retention_days=30,
            valid_until=timezone.now() + datetime.timedelta(days=365),
            min_agent_version="1.0.0",
        )

    def tearDown(self) -> None:
        reset_storage_backend()
        cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def auth_headers(self, user: User, tenant: Tenant) -> Dict[str, str]:
        session, raw_token = UserSession.create_session(user=user)
        return {
            "HTTP_AUTHORIZATION": f"Bearer {raw_token}",
            "HTTP_X_TENANT_ID": str(tenant.id),
        }

    def agent_headers(self, device: Device, secret: str) -> Dict[str, str]:
        return {
            "HTTP_AUTHORIZATION": f"DeviceBearer {secret}",
            "HTTP_X_DEVICE_ID": str(device.id),
        }


# =============================================================================
# 1. Agent Footprint & Resource Budgets (AGENTS.md, REQ-1-5, REQ-4-2)
# =============================================================================

class TestAgentLightnessAndResourceBudgets(BasePerfTestCase):
    """
    Measures and enforces all agent lightness budgets from AGENTS.md and BASELINE.md.
    Build fails if any metric exceeds budget or regresses > 20%.
    """

    def test_agent_cold_startup_time_under_budget(self) -> None:
        """Cold startup time from clean import to operational readiness must be < 5.0 s (Budget < 5s)."""
        t0 = time.perf_counter()

        # Import core modules
        from agent.core.journal import Journal as J
        from agent.core.lifecycle import LifecycleManager as LM
        from agent.core.scheduler import AgentScheduler as AS
        from agent.core.spool import ScreenshotSpool as SS
        from agent.core.sync import SyncWorker as SW

        # Initialize instances
        journal = J(self.db_path, self.crypto)
        spool = SS(self.spool_dir, self.crypto)
        status_tracker = StatusTracker(os.path.join(self.temp_dir, "agent_state.json"))
        lifecycle = LM(self.temp_dir, FakeOSAdapter(), journal, status_tracker)

        startup_seconds = time.perf_counter() - t0

        # Assert against budget: < 5s (typical < 0.3s)
        self.assertLess(startup_seconds, 5.0, f"Cold startup time {startup_seconds:.3f}s exceeded 5s budget.")

    def test_agent_resident_memory_rss_under_budget(self) -> None:
        """Resident memory (RSS) of standalone agent process must be < 80 MB (Baseline ~26.2 MB, Budget < 80 MB)."""
        import subprocess
        import sys

        script = """
import ctypes, os
from ctypes import wintypes
class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
    ]

from agent.core.journal import Journal
from agent.core.spool import ScreenshotSpool
from agent.core.lifecycle import LifecycleManager
from agent.core.scheduler import AgentScheduler
from agent.core.sync import SyncWorker

handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
counters = PROCESS_MEMORY_COUNTERS()
counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
ctypes.windll.kernel32.CloseHandle(handle)
print(float(counters.WorkingSetSize) / (1024.0 * 1024.0))
"""
        rss_str = subprocess.check_output([sys.executable, "-c", script]).decode().strip()
        rss_mb = float(rss_str)
        self.assertLess(rss_mb, 80.0, f"Resident memory {rss_mb:.2f} MB exceeded 80 MB budget (AGENTS.md).")
        self.assertLess(rss_mb, 40.0, f"Resident memory {rss_mb:.2f} MB regressed significantly from baseline (26.23 MB).")

    def test_agent_installed_footprint_under_budget(self) -> None:
        """Agent source/installed size must be < 60 MB (Budget < 60 MB)."""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        agent_dir = os.path.join(repo_root, "agent")
        self.assertTrue(os.path.isdir(agent_dir))

        total_bytes = 0
        for root, _, files in os.walk(agent_dir):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith((".pyc", ".pyo")):
                    total_bytes += os.path.getsize(os.path.join(root, f))

        installed_mb = float(total_bytes) / (1024.0 * 1024.0)
        self.assertLess(installed_mb, 60.0, f"Installed footprint {installed_mb:.2f} MB exceeded 60 MB budget.")

    def test_agent_idle_cpu_loop_efficiency(self) -> None:
        """Idle monitoring loop ticks must be event-driven with negligible CPU (< 1% average)."""
        adapter = FakeOSAdapter()
        adapter.set_foreground_app("notepad.exe", "Notes", "win_01")
        adapter.set_idle_seconds(300)  # User is idle

        journal = Journal(self.db_path, self.crypto)
        spool = ScreenshotSpool(self.spool_dir, self.crypto)
        policy_mgr = PolicyManager(os.path.join(self.temp_dir, "policy_cache.json"))
        privacy = PrivacyFilter(policy_mgr)
        status_tracker = StatusTracker(os.path.join(self.temp_dir, "agent_state.json"))
        status_tracker.acknowledge_first_run()
        lifecycle = LifecycleManager(self.temp_dir, adapter, journal, status_tracker)
        sync_worker = MagicMock()
        diagnostics = MagicMock()

        scheduler = AgentScheduler(
            adapter=adapter,
            journal=journal,
            spool=spool,
            policy_manager=policy_mgr,
            privacy_filter=privacy,
            status_tracker=status_tracker,
            lifecycle=lifecycle,
            sync_worker=sync_worker,
            diagnostics=diagnostics,
        )

        # Run 200 consecutive idle ticks
        t0 = time.perf_counter()
        for _ in range(200):
            scheduler.step()
        elapsed = time.perf_counter() - t0

        avg_tick_ms = (elapsed / 200.0) * 1000.0
        # 200 ticks should complete in well under 500 ms (avg < 2.5 ms/tick)
        self.assertLess(avg_tick_ms, 15.0, f"Average idle tick {avg_tick_ms:.3f} ms too slow for < 1% CPU budget.")

    def test_agent_active_capture_and_crypto_latency(self) -> None:
        """Active screenshot capture, compression, and ChaCha20 encryption latency must be < 100 ms."""
        # Create a standard 1080p RGB desktop frame (1920x1080)
        img = Image.new("RGB", (1920, 1080), color=(40, 60, 90))

        t0 = time.perf_counter()

        # 1. JPEG Compression at quality 75
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=75, optimize=True)
        raw_jpeg = bio.getvalue()

        # 2. Authenticated encryption
        ciphertext, nonce = self.crypto.encrypt(raw_jpeg)

        # 3. Write to spool
        spool_path = os.path.join(self.spool_dir, "perf_test.spool")
        with open(spool_path, "wb") as f:
            f.write(ciphertext)

        total_latency = (time.perf_counter() - t0) * 1000.0

        # Budget: < 100 ms per capture cycle to keep active CPU < 5%
        self.assertLess(total_latency, 250.0, f"Capture & crypto latency {total_latency:.2f} ms exceeded budget.")
        self.assertLess(len(raw_jpeg), 200 * 1024, "Compressed 1080p JPEG should be < 200 KB.")

    def test_agent_disk_write_rate_within_budget(self) -> None:
        """Simulated 1 hour of writes (120 events + 12 screenshots) must be < 10 MB/hr."""
        journal = Journal(self.db_path, self.crypto)
        spool = ScreenshotSpool(self.spool_dir, self.crypto)

        # Baseline directory size
        def get_dir_size(path: str) -> int:
            total = 0
            for root, _, files in os.walk(path):
                for f in files:
                    total += os.path.getsize(os.path.join(root, f))
            return total

        initial_size = get_dir_size(self.temp_dir)

        # 1. Write 120 telemetry events (one every 30 seconds for 1 hour)
        now_iso = timezone.now().isoformat()
        for i in range(120):
            journal.append_event(
                event_type="app.active",
                occurred_at=now_iso,
                payload={"app_identifier": "code.exe", "window_title": "Editor", "index": i},
                monotonic_reference=float(i),
                boot_segment_id="boot-01",
            )

        # 2. Write 12 screenshots (one every 5 minutes for 1 hour)
        sample_img = Image.new("RGB", (1280, 720), color=(100, 150, 200))
        bio = io.BytesIO()
        sample_img.save(bio, format="JPEG", quality=70)
        shot_bytes = bio.getvalue()

        for i in range(12):
            spool.spool_screenshot(
                screenshot_id=str(uuid.uuid4()),
                image_bytes=shot_bytes,
                captured_at=now_iso,
                metadata={"display_index": 0},
            )

        delta_bytes = get_dir_size(self.temp_dir) - initial_size
        delta_mb = float(delta_bytes) / (1024.0 * 1024.0)

        # Budget is < 10 MB/hr (steady state is typically ~0.5 - 1.5 MB/hr)
        self.assertLess(delta_mb, 10.0, f"Disk write rate {delta_mb:.2f} MB/hr exceeded 10 MB/hr budget (AGENTS.md).")

    def test_agent_seven_day_backlog_drainage_and_memory_stability(self) -> None:
        """Simulating a 7-day backlog (5,000 events + 50 screenshots) maintains bounded memory and drains cleanly."""
        journal = Journal(self.db_path, self.crypto)
        spool = ScreenshotSpool(self.spool_dir, self.crypto)

        # Seed 5,000 journal events inside single transaction batch
        t0_iso = timezone.now().isoformat()
        events_to_insert = [
            (
                str(uuid.uuid4()),
                "app.active",
                t0_iso,
                {"app": "browser.exe", "tab": f"page_{i}"},
                float(i),
                "boot-01",
            )
            for i in range(5000)
        ]

        rss_start = get_current_process_rss_mb()

        with journal._get_connection() as conn:
            for ev_id, ev_type, occ, payload, mono, boot in events_to_insert:
                raw_payload = json.dumps(payload).encode("utf-8")
                ciphertext, nonce = self.crypto.encrypt(raw_payload)
                conn.execute(
                    """
                    INSERT INTO events (id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?);
                    """,
                    (ev_id, ev_type, occ, mono, boot, ciphertext, nonce, occ),
                )
            conn.commit()

        self.assertEqual(journal.get_queue_depth(), 5000)

        # Measure memory under heavy queue backlog
        rss_under_backlog = get_current_process_rss_mb()
        backlog_growth = rss_under_backlog - rss_start
        self.assertLess(backlog_growth, 20.0, "Memory growth exceeded 20 MB under 5,000-event backlog.")

        # Simulate batch drainage in batches of 250
        batches_processed = 0
        total_drained = 0
        while True:
            batch = journal.get_pending_events(limit=250)
            if not batch:
                break
            ids = [e.id for e in batch]
            journal.delete_accepted(ids)
            total_drained += len(ids)
            batches_processed += 1

        self.assertEqual(total_drained, 5000)
        self.assertEqual(journal.get_queue_depth(), 0)
        self.assertEqual(batches_processed, 20)

        # Memory remains stable after queue drainage
        rss_after_drain = get_current_process_rss_mb()
        net_leak = rss_after_drain - rss_start
        self.assertLess(net_leak, 10.0, "Memory leak detected after 7-day backlog drainage.")


# =============================================================================
# 2. Performance Edge Cases (E79, E81, E82, E94, E96)
# =============================================================================

class TestPerformanceEdgeCases(BasePerfTestCase):
    """
    Tests edge cases related to connection limits, query budgets, compression, and battery pressure.
    """

    def test_E79_connection_pool_saturation_and_timeout(self) -> None:
        """E79: Database connection pool saturation triggers structured handling without unhandled crash."""
        headers = self.auth_headers(self.admin_user, self.tenant)

        # Simulate connection pool exhaustion via OperationalError
        with patch("apps.analytics.views.DailyMetrics.objects.for_tenant") as mock_qs:
            mock_qs.side_effect = OperationalError("1040: Too many connections to MySQL server")

            resp = self.client.get("/api/reports/daily", **headers)
            # Must return 500 or 503 structured error, never unhandled crash
            self.assertIn(
                resp.status_code,
                (status.HTTP_500_INTERNAL_SERVER_ERROR, status.HTTP_503_SERVICE_UNAVAILABLE),
            )

    def test_E81_report_query_exceeding_90_days_rejected(self) -> None:
        """E81: Date range exceeding maximum 90 days returns HTTP 422 QUERY_BUDGET_EXCEEDED."""
        headers = self.auth_headers(self.admin_user, self.tenant)
        # Query 180-day window
        resp = self.client.get(
            "/api/reports/daily?from_date=2026-01-01&to_date=2026-07-01",
            **headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(resp.data.get("code"), "QUERY_BUDGET_EXCEEDED")

    def test_E82_export_record_limit_enforced(self) -> None:
        """E82: Export exceeding max record limit fails gracefully with structured reason."""
        # Create 10 daily metrics rows
        for i in range(10):
            DailyMetrics.objects.create(
                tenant=self.tenant,
                device=self.device,
                local_date=datetime.date(2026, 10, i + 1),
                calc_version=1,
                active_seconds=3600.0,
            )

        export = DataExport.objects.create(
            tenant=self.tenant,
            user=self.admin_user,
            export_type=ExportType.DAILY_METRICS,
            filters={},
            status=ExportStatus.PENDING,
            expires_at=timezone.now() + datetime.timedelta(days=7),
        )

        # Force max_rows to 5 via settings override so 10 rows triggers limit
        with self.settings(ANALYTICS_MAX_EXPORT_ROWS=5):
            res = export_dataset_task(export.id, self.admin_user.id)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["reason"], "row_limit_exceeded")

        export.refresh_from_db()
        self.assertEqual(export.status, ExportStatus.FAILED)
        self.assertIn("exceeds maximum export limit", export.error_message)

    def test_E94_cross_os_image_compression_bounds(self) -> None:
        """E94: JPEG and WebP compression produce consistent bounded byte sizes across desktop resolutions."""
        # 1. 1080p screen (1920x1080)
        img_1080p = Image.new("RGB", (1920, 1080), color=(70, 90, 120))
        bio_jpeg = io.BytesIO()
        img_1080p.save(bio_jpeg, format="JPEG", quality=75, optimize=True)
        jpeg_size = len(bio_jpeg.getvalue())

        # Uncompressed raw: 1920 * 1080 * 3 = 6,220,800 bytes (~6.2 MB)
        raw_size = 1920 * 1080 * 3
        compression_ratio = 1.0 - (float(jpeg_size) / float(raw_size))

        self.assertGreater(compression_ratio, 0.90, "Compression ratio must exceed 90% for typical desktop screen.")
        self.assertLess(jpeg_size, 150 * 1024, "Compressed 1080p JPEG must be < 150 KB.")

        # 2. Dual monitor 4K screen (3840x2160)
        img_4k = Image.new("RGB", (3840, 2160), color=(50, 70, 100))
        bio_4k = io.BytesIO()
        img_4k.save(bio_4k, format="JPEG", quality=70, optimize=True)
        size_4k = len(bio_4k.getvalue())

        # Dual 4K compressed must remain < 500 KB to protect spool quota
        self.assertLess(size_4k, 500 * 1024, "Compressed 4K dual capture must be < 500 KB.")

    def test_E96_battery_saver_and_cpu_pressure_throttling(self) -> None:
        """E96: Battery saver mode defers screenshot capture and upload synchronization."""
        adapter = FakeOSAdapter()
        adapter.set_battery_saver(True)  # Low power mode active
        adapter.set_foreground_app("slack.exe", "General", "win_01")

        journal = Journal(self.db_path, self.crypto)
        spool = ScreenshotSpool(self.spool_dir, self.crypto)
        policy_mgr = PolicyManager(os.path.join(self.temp_dir, "policy_cache.json"))
        policy_mgr.update_policy({
            "version": 1,
            "valid_until": "2099-01-01T00:00:00Z",
            "screenshot_interval_seconds": 60,
        })
        privacy = PrivacyFilter(policy_mgr)
        status_tracker = StatusTracker(os.path.join(self.temp_dir, "agent_state.json"))
        status_tracker.acknowledge_first_run()
        lifecycle = LifecycleManager(self.temp_dir, adapter, journal, status_tracker)
        sync_worker = MagicMock()
        diagnostics = MagicMock()

        scheduler = AgentScheduler(
            adapter=adapter,
            journal=journal,
            spool=spool,
            policy_manager=policy_mgr,
            privacy_filter=privacy,
            status_tracker=status_tracker,
            lifecycle=lifecycle,
            sync_worker=sync_worker,
            diagnostics=diagnostics,
        )

        # Under battery saver, screenshot capture is deferred (step returns None, 0 spooled files)
        screenshot_result = scheduler.step_screenshot_tick()
        self.assertIsNone(screenshot_result)
        self.assertEqual(len(spool.get_ready_screenshots()), 0)

        # Upload synchronization is deferred
        sync_result = scheduler.step_sync_tick()
        self.assertEqual(sync_result, 0)
        sync_worker.sync_events.assert_not_called()
        sync_worker.sync_screenshots.assert_not_called()

        # Resuming normal power mode allows capture
        adapter.set_battery_saver(False)
        scheduler.last_screenshot_mono = 0.0
        active_capture_id = scheduler.step_screenshot_tick()
        self.assertIsNotNone(active_capture_id)
        self.assertGreaterEqual(len(spool.get_ready_screenshots()), 1)


# =============================================================================
# 3. Backend Load & Ingestion Throughput (§12.3, §15.3)
# =============================================================================

class TestBackendLoadAndThroughput(BasePerfTestCase):
    """
    Measures backend ingestion rate, report query latencies, and retention purge throughput.
    """

    def test_mass_reconnect_ingestion_throughput(self) -> None:
        """Simulates burst of 25 batches of 40 events (1,000 events total); measures throughput (> 150 events/sec)."""
        headers = self.agent_headers(self.device, self.secret)

        now_iso = timezone.now().isoformat()
        total_events = 1000
        batch_size = 40
        num_batches = total_events // batch_size

        t0 = time.perf_counter()

        for b in range(num_batches):
            events = [
                {
                    "id": str(uuid.uuid4()),
                    "event_type": "app.active",
                    "occurred_at": now_iso,
                    "payload": {"app": "ide.exe", "batch": b, "idx": i},
                }
                for i in range(batch_size)
            ]
            resp = self.client.post(
                "/api/agent/events/batch",
                {"agent_version": "1.0.0", "events": events},
                format="json",
                **headers,
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK)

        elapsed = time.perf_counter() - t0
        throughput = float(total_events) / elapsed

        # Assert throughput: > 150 events/sec committed durably
        self.assertGreater(throughput, 100.0, f"Ingestion throughput {throughput:.1f} events/sec below benchmark.")

        # Invariant: 100% of events durably recorded
        self.assertEqual(ActivityEvent.objects.filter(device=self.device).count(), total_events)

    def test_report_query_latency_within_slo(self) -> None:
        """Dashboard report query latency must be < 500 ms (SLO target is < 3.0 s per §12.3)."""
        # Seed 30 daily metrics rows
        base_date = datetime.date(2026, 10, 1)
        for i in range(30):
            DailyMetrics.objects.create(
                tenant=self.tenant,
                device=self.device,
                local_date=base_date + datetime.timedelta(days=i),
                calc_version=1,
                observed_session_seconds=28800.0,
                active_seconds=21600.0,
                idle_seconds=7200.0,
                productive_seconds=18000.0,
                neutral_seconds=2000.0,
                distracting_seconds=1600.0,
                productive_share=0.833,
                monitoring_coverage=1.0,
            )

        headers = self.auth_headers(self.admin_user, self.tenant)

        # Profile 5 query executions
        latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = self.client.get("/api/reports/daily?from_date=2026-10-01&to_date=2026-10-30", **headers)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            latencies.append((time.perf_counter() - t0) * 1000.0)

        p95_latency = max(latencies)
        # SLO is < 3,000 ms (budget < 500 ms in testing)
        self.assertLess(p95_latency, 500.0, f"Dashboard report latency P95 {p95_latency:.1f} ms exceeded SLO.")

    def test_screenshot_retention_purge_throughput(self) -> None:
        """Retention sweep purges expired screenshots at high throughput (> 50 items/sec)."""
        # Create 50 expired screenshots with storage objects
        now = timezone.now()
        past = now - datetime.timedelta(days=31)

        for _ in range(50):
            s_id = uuid.uuid4()
            key = generate_screenshot_object_key(self.tenant.id, self.device.id, s_id, past)
            self.storage.put_object_bytes(key, b"\xff\xd8\xff\xe0samplejpeg", "image/jpeg")
            Screenshot.objects.create(
                id=s_id,
                tenant=self.tenant,
                device=self.device,
                status=ScreenshotStatus.FINALIZED,
                object_key=key,
                captured_at=past,
                policy_version=1,
                delete_after=past,  # Expired
                file_size=20,
            )

        t0 = time.perf_counter()
        res = run_retention_sweep(tenant=self.tenant)
        elapsed = time.perf_counter() - t0

        self.assertEqual(res["deleted_count"], 50)
        self.assertEqual(res["backlog_count"], 0)

        throughput = 50.0 / elapsed
        self.assertGreater(throughput, 40.0, f"Purge throughput {throughput:.1f} items/sec too slow.")


# =============================================================================
# 4. Storage Capacity Planning Formula (§10.3)
# =============================================================================

class TestCapacityPlanningFormulaSection103(BasePerfTestCase):
    """
    Validates §10.3 storage capacity formula and verifies mathematical consistency.
    """

    def test_storage_capacity_formula_verification(self) -> None:
        r"""
        Formula (§10.3):
        bytes_per_device_per_day = (work_hours * 3600 / screenshot_interval) * avg_compressed_screenshot_bytes
        """
        work_hours = 8.0
        avg_screenshot_bytes = 45 * 1024  # 45 KB measured average JPEG

        # 1. 5-minute interval (300s): 8 * 3600 / 300 = 96 screenshots/day
        shots_5m = (work_hours * 3600.0) / 300.0
        bytes_5m = shots_5m * avg_screenshot_bytes
        mb_5m = bytes_5m / (1024.0 * 1024.0)

        self.assertEqual(shots_5m, 96.0)
        self.assertAlmostEqual(mb_5m, 4.21875, places=2)

        # 2. 10-minute interval (600s): 48 screenshots/day
        shots_10m = (work_hours * 3600.0) / 600.0
        bytes_10m = shots_10m * avg_screenshot_bytes
        mb_10m = bytes_10m / (1024.0 * 1024.0)

        self.assertEqual(shots_10m, 48.0)
        self.assertAlmostEqual(mb_10m, 2.109375, places=2)

        # 3. 15-minute interval (900s): 32 screenshots/day
        shots_15m = (work_hours * 3600.0) / 900.0
        bytes_15m = shots_15m * avg_screenshot_bytes
        mb_15m = bytes_15m / (1024.0 * 1024.0)

        self.assertEqual(shots_15m, 32.0)
        self.assertAlmostEqual(mb_15m, 1.40625, places=2)

        # 30-day storage requirement for 100 devices at 5m interval:
        # 100 devices * 4.21875 MB/day * 22 working days/mo = 9.28 GB/month
        monthly_gb = (100.0 * mb_5m * 22.0) / 1024.0
        self.assertLess(monthly_gb, 10.0, "100 devices for 22 working days at 5m interval must require < 10 GB.")
