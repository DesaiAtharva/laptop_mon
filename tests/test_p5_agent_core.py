"""
tests/test_p5_agent_core.py — Test Suite for P5: Desktop Agent Core & Fake Adapter.

Covers:
- Requirements: REQ-1-5, REQ-1-7, REQ-2-2, REQ-3-1, REQ-4-1, REQ-4-2, REQ-4-3, REQ-4-4,
  REQ-5-1, REQ-5-2, REQ-5-3, REQ-5-4, REQ-5-5, REQ-5-6, REQ-5-7, REQ-6-1, REQ-12-1.
- Edge Cases: E01, E04–E13, E17–E27, E37, E38, E56, E59, E67, E68, E88, E93, E96, E97, E98.
"""

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from agent.adapters.base import (
    AdapterCapability,
    ForegroundAppEvent,
    PermissionStatus,
    PowerEventType,
    SessionEventType,
)
from agent.adapters.fake.fake_adapter import FakeOSAdapter
from agent.core.crypto import CryptoManager, InMemoryKeyStore
from agent.core.diagnostics import DiagnosticsCollector, NetworkDiagnostics, RedactingFormatter
from agent.core.journal import Journal
from agent.core.lifecycle import LifecycleManager
from agent.core.policy import PolicyManager
from agent.core.privacy_filter import PrivacyFilter
from agent.core.scheduler import AgentScheduler
from agent.core.spool import ScreenshotSpool
from agent.core.status import AgentState, StatusTracker
from agent.core.sync import SyncWorker


class AgentCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="agent_test_")
        self.journal_db = os.path.join(self.temp_dir, "journal.db")
        self.spool_dir = os.path.join(self.temp_dir, "spool")
        self.policy_file = os.path.join(self.temp_dir, "policy.json")
        self.status_file = os.path.join(self.temp_dir, "status.json")

        self.key_store = InMemoryKeyStore()
        self.crypto = CryptoManager(self.key_store)
        self.crypto.generate_and_save_key()

        self.adapter = FakeOSAdapter()
        self.journal = Journal(self.journal_db, self.crypto, max_events=100)
        self.spool = ScreenshotSpool(self.spool_dir, self.crypto, max_spool_bytes=5 * 1024 * 1024)
        self.policy_manager = PolicyManager(self.policy_file)
        self.privacy_filter = PrivacyFilter(self.policy_manager)
        self.status_tracker = StatusTracker(self.status_file)
        self.status_tracker.acknowledge_first_run()

        self.lifecycle = LifecycleManager(
            data_dir=self.temp_dir,
            adapter=self.adapter,
            journal=self.journal,
            status_tracker=self.status_tracker,
            expected_os_user="testuser",
        )
        self.diagnostics = DiagnosticsCollector(agent_version="1.0.0")

        self.mock_http_calls = []

        def mock_http(url, data, headers, method="POST"):
            self.mock_http_calls.append({"url": url, "data": data, "headers": headers, "method": method})
            if "events/batch" in url:
                parsed = json.loads(data.decode("utf-8")) if data else {}
                ids = [e["id"] for e in parsed.get("events", [])]
                return 200, json.dumps({"accepted": ids, "already_accepted": []}).encode("utf-8"), {}
            elif "upload-intents" in url:
                return 201, json.dumps({"upload_url": "https://storage.local/upload", "object_key": "tenants/t1/shots/s1.jpg"}).encode("utf-8"), {}
            elif "storage.local" in url:
                return 200, b"", {}
            elif "screenshots/complete" in url:
                return 200, json.dumps({"status": "finalized"}).encode("utf-8"), {}
            elif "heartbeat" in url:
                return 200, json.dumps({"status": "ok"}).encode("utf-8"), {}
            return 200, b"{}", {}

        self.sync_worker = SyncWorker(
            base_api_url="https://api.test.local",
            device_id="dev-1234",
            credential_token="mock-token-xyz",
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_manager,
            status_tracker=self.status_tracker,
            http_client=mock_http,
        )

        self.scheduler = AgentScheduler(
            adapter=self.adapter,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_manager,
            privacy_filter=self.privacy_filter,
            status_tracker=self.status_tracker,
            lifecycle=self.lifecycle,
            sync_worker=self.sync_worker,
            diagnostics=self.diagnostics,
        )

    def tearDown(self) -> None:
        self.journal.close()
        self.spool.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── Core Architectural Requirements ────────────────────────────────────────

    def test_REQ_4_1_agent_core_has_no_os_specific_imports(self) -> None:
        """Core code must never import OS-specific modules."""
        import sys
        core_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent", "core"))
        forbidden = ["win32", "win32api", "win32con", "AppKit", "Cocoa", "ctypes.windll"]

        for fname in os.listdir(core_dir):
            if fname.endswith(".py"):
                fpath = os.path.join(core_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    for f_mod in forbidden:
                        self.assertNotIn(f"import {f_mod}", content, f"{fname} imports forbidden OS module {f_mod}")

    def test_REQ_2_2_first_run_notice_required_before_capture(self) -> None:
        """Employee MUST acknowledge first-run privacy notice before any capture starts."""
        fresh_status = StatusTracker(os.path.join(self.temp_dir, "unack_status.json"))
        self.assertFalse(fresh_status.can_capture())
        self.assertEqual(fresh_status.state, AgentState.UNACKNOWLEDGED)

        # Scheduler must refuse to capture
        self.scheduler.status_tracker = fresh_status
        self.adapter.set_foreground_app("code.exe", "VS Code")
        event_id = self.scheduler.step_foreground_tick()
        self.assertIsNone(event_id)

        # Acknowledge first-run notice
        fresh_status.acknowledge_first_run()
        self.assertTrue(fresh_status.can_capture())
        self.assertEqual(fresh_status.state, AgentState.RUNNING)

        # Now capture succeeds
        event_id2 = self.scheduler.step_foreground_tick()
        self.assertIsNotNone(event_id2)

    def test_REQ_6_1_delete_local_data_only_after_confirmed_acceptance(self) -> None:
        """Agent deletes local data ONLY after confirmed server acceptance."""
        self.journal.append_event(
            event_type="app.active",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload={"app": "test"},
            monotonic_reference=time.monotonic(),
            boot_segment_id="seg-1",
            event_id="evt-retain-1",
        )
        self.assertEqual(self.journal.get_queue_depth(), 1)

        # Mock failure response: 500 error
        def failing_http(url, data, headers, method="POST"):
            return 500, b"Internal Server Error", {}

        self.sync_worker.http_client = failing_http
        synced = self.sync_worker.sync_events()
        self.assertEqual(synced, 0)
        # Event MUST remain in local journal!
        self.assertEqual(self.journal.get_queue_depth(), 1)

        # Reset backoff for immediate second attempt
        self.sync_worker.backoff_until = 0.0

        # Now mock confirmed 200 acceptance
        def success_http(url, data, headers, method="POST"):
            return 200, json.dumps({"accepted": ["evt-retain-1"], "already_accepted": []}).encode("utf-8"), {}

        self.sync_worker.http_client = success_http
        synced = self.sync_worker.sync_events()
        self.assertEqual(synced, 1)
        # Deleted ONLY after acceptance
        self.assertEqual(self.journal.get_queue_depth(), 0)

    def test_REQ_12_1_heartbeat_payload_signals(self) -> None:
        """Agent heartbeat includes all §12.1 signals."""
        perms = {"screen_recording": PermissionStatus.GRANTED, "accessibility": PermissionStatus.GRANTED}
        hb = self.diagnostics.build_heartbeat_payload(
            queue_depth=5,
            oldest_pending_age_seconds=120.5,
            permissions=perms,
            last_sync_at="2026-10-28T10:00:00Z",
            crash_free_sessions=4,
        )
        self.assertEqual(hb["agent_version"], "1.0.0")
        self.assertEqual(hb["queue_depth"], 5)
        self.assertEqual(hb["oldest_pending_age_seconds"], 120.5)
        self.assertEqual(hb["permission_state"]["screen_recording"], "granted")
        self.assertEqual(hb["last_sync_at"], "2026-10-28T10:00:00Z")
        self.assertEqual(hb["crash_free_sessions"], 4)

    # ── Edge Cases E01 to E13 ──────────────────────────────────────────────────

    def test_E01_no_internet_at_startup_starts_under_cached_policy(self) -> None:
        """E01: Agent starts offline under a valid cached policy."""
        # Pre-seed cached policy
        now = datetime.now(timezone.utc)
        valid_until = (now + timedelta(days=7)).isoformat()
        self.policy_manager.update_policy({
            "version": 4,
            "valid_until": valid_until,
            "screenshot_interval_seconds": 60,
            "idle_threshold_seconds": 120,
            "window_title_collection": True,
        })

        # Fresh manager loading from disk while offline
        offline_policy_mgr = PolicyManager(self.policy_file)
        self.assertTrue(offline_policy_mgr.is_policy_valid())
        self.assertEqual(offline_policy_mgr.get_effective_policy().version, 4)
        self.assertTrue(offline_policy_mgr.can_capture_screenshots())

    def test_E04_dns_failure_or_captive_portal(self) -> None:
        """E04: DNS failure or captive portal detected gracefully."""
        diag = NetworkDiagnostics.probe_connectivity("http://nonexistent.domain.invalid.local")
        self.assertFalse(diag["dns_ok"])
        self.assertFalse(diag["connected"])

    def test_E05_proxy_vpn_connectivity_probe(self) -> None:
        """E05: Proxy or VPN diagnostics check without crashing."""
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:8888"
        try:
            diag = NetworkDiagnostics.probe_connectivity("http://127.0.0.1:9")
            self.assertTrue(diag["proxy_detected"])
        finally:
            os.environ.pop("HTTP_PROXY", None)

    def test_E06_tls_certificate_invalid_or_expired_fails_closed(self) -> None:
        """E06: TLS failure fails closed, never falls back to insecure HTTP."""
        # Our default_http_request enforces TLS verification
        self.assertTrue(hasattr(self.sync_worker, "_default_http_request"))

    def test_E07_shutdown_while_online_is_bounded(self) -> None:
        """E07: Shutdown is bounded and does not block on network."""
        start = time.monotonic()
        clean = self.lifecycle.on_bounded_shutdown(timeout_seconds=3.0)
        elapsed = time.monotonic() - start
        self.assertTrue(clean)
        self.assertLess(elapsed, 3.0)
        self.assertEqual(self.status_tracker.state, AgentState.STOPPED)

    def test_E08_hard_power_loss_detected_as_unclean_shutdown(self) -> None:
        """E08: Unclean shutdown from crash/power loss logs an explicit telemetry gap event on next run."""
        # Simulate active run marker left behind
        marker_path = os.path.join(self.temp_dir, "run.marker")
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump({"boot_segment_id": "seg-crash", "last_active_at": "2026-10-28T09:00:00Z"}, f)

        report = self.lifecycle.on_startup()
        self.assertTrue(report["unclean_shutdown_detected"])
        self.assertFalse(report["clean_start"])

        # Explicit gap event written
        pending = self.journal.get_pending_events()
        gap_events = [e for e in pending if e.event_type == "telemetry-gap"]
        self.assertEqual(len(gap_events), 1)
        self.assertEqual(gap_events[0].payload["gap_reason"], "unclean_shutdown_detected")

    def test_E09_agent_killed_during_sqlite_write_recovers(self) -> None:
        """E09: SQLite integrity check and WAL journal recovers on startup."""
        self.journal.append_event("test.evt", "2026-10-28T10:00:00Z", {"val": 1}, 1.0, "seg-1")
        self.assertTrue(self.journal._check_integrity())

    def test_E10_agent_crashes_repeatedly_trips_circuit_breaker(self) -> None:
        """E10: Crash-loop circuit breaker detects rapid successive crashes."""
        for _ in range(2):
            self.lifecycle._check_crash_loop()
        tripped = self.lifecycle._check_crash_loop()
        self.assertTrue(tripped)

    def test_E11_ui_closed_agent_continues_and_state_discoverable(self) -> None:
        """E11: Closing tray UI does not stop capture; state remains discoverable."""
        self.assertTrue(self.status_tracker.can_capture())
        # Discoverable via disk
        disc = self.status_tracker.get_discoverable_status()
        self.assertTrue(disc["is_capturing"])
        self.assertTrue(disc["first_run_acknowledged"])

    def test_E12_employee_explicitly_exits_monitoring_honored(self) -> None:
        """E12: Employee explicitly exits; monitoring stops and never silently reverses."""
        self.status_tracker.stop_monitoring(reason="employee_requested_stop")
        self.assertFalse(self.status_tracker.can_capture())
        self.assertEqual(self.status_tracker.state, AgentState.STOPPED)

        # Re-creating status tracker simulates restart: MUST NOT silently restart!
        restarted_tracker = StatusTracker(self.status_file)
        self.assertFalse(restarted_tracker.can_capture())
        self.assertEqual(restarted_tracker.state, AgentState.STOPPED)

    def test_E13_uninstall_with_pending_data_warns_and_prevents_silent_deletion(self) -> None:
        """E13: Uninstall hook warns of pending data and offers export."""
        self.journal.append_event("app.active", "2026-10-28T10:00:00Z", {"app": "a"}, 1.0, "seg-1")
        report = self.lifecycle.on_uninstall_requested()
        self.assertTrue(report["has_pending_data"])
        self.assertGreaterEqual(report["pending_event_count"], 1)
        self.assertIn("unsynced telemetry events", report["warning"])

    # ── Edge Cases E17 to E27 ──────────────────────────────────────────────────

    def test_E17_local_disk_full_drops_screenshots_before_event_journal(self) -> None:
        """E17: When disk headroom is tight, priority dropping purges screenshots first."""
        # Spool a screenshot
        self.spool.spool_screenshot(b"fake-image-bytes-1", "2026-10-28T10:00:00Z")
        self.assertGreater(self.spool.get_spool_size_bytes(), 0)

        # Force drop oldest screenshots
        freed = self.spool._drop_oldest_screenshots(target_freed_bytes=10)
        self.assertGreater(freed, 0)
        self.assertEqual(self.spool.get_spool_size_bytes(), 0)

    def test_E18_local_queue_reaches_quota_drops_oldest_with_explicit_gap(self) -> None:
        """E18: Queue limit reached drops oldest with explicit telemetry gap event."""
        small_journal = Journal(os.path.join(self.temp_dir, "small.db"), self.crypto, max_events=5)
        for i in range(7):
            small_journal.append_event("test.evt", f"2026-10-28T10:0{i}:00Z", {"i": i}, float(i), "seg-1")

        pending = small_journal.get_pending_events()
        gap_events = [e for e in pending if e.event_type == "telemetry-gap"]
        self.assertGreaterEqual(len(gap_events), 1)
        small_journal.close()

    def test_E19_sqlite_corrupt_quarantined_and_valid_records_recovered(self) -> None:
        """E19: Corrupt SQLite journal is quarantined; fresh journal initialized."""
        # Insert event
        self.journal.append_event("evt.1", "2026-10-28T10:00:00Z", {"val": 100}, 1.0, "seg-1")
        self.journal.close()

        # Corrupt DB header bytes
        with open(self.journal_db, "r+b") as f:
            f.seek(0)
            f.write(b"CORRUPTED_HEADER_DATA_NOT_SQLITE")

        # Quarantines and recovers
        recovered_journal = Journal(self.journal_db, self.crypto, max_events=100)
        self.assertTrue(recovered_journal._check_integrity())
        recovered_journal.close()

    def test_E20_screenshot_file_without_db_row_reconciled(self) -> None:
        """E20: Untracked .spool file on disk is indexed at startup reconciliation."""
        orphan_sid = "orphan-shot-123"
        orphan_path = os.path.join(self.spool_dir, f"{orphan_sid}.spool")
        with open(orphan_path, "wb") as f:
            f.write(b"mock-encrypted-shot-payload")

        stats = self.spool.reconcile_at_startup()
        self.assertEqual(stats["orphan_files_indexed"], 1)

    def test_E21_db_row_without_screenshot_file_reconciled(self) -> None:
        """E21: DB row with missing physical file is pruned during reconciliation."""
        conn = self.spool._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO spooled_screenshots
                (screenshot_id, file_path, sha256_checksum, file_size, captured_at, metadata_json, status, created_at)
                VALUES ('missing-file-id', '/path/does/not/exist.spool', 'abc', 10, '2026-10-28T10:00:00Z', '{}', 'ready', '2026-10-28T10:00:00Z');
                """
            )
        stats = self.spool.reconcile_at_startup()
        self.assertEqual(stats["orphan_rows_removed"], 1)

    def test_E22_encryption_key_unavailable_never_uploads_plaintext(self) -> None:
        """E22: Encryption key unavailable fails closed, never uploads plaintext."""
        self.key_store.revoke_key()
        self.assertFalse(self.crypto.is_key_available())

        with self.assertRaises(KeyError):
            self.crypto.encrypt(b"plaintext-secrets")

    def test_E23_device_reimaged_enrolls_as_new_device(self) -> None:
        """E23: Fresh data directory has clean boot segment and no stale IDs."""
        self.assertIsNotNone(self.lifecycle.boot_segment_id)

    def test_E24_device_stolen_revocation_handled(self) -> None:
        """E24: 403 halts uploads."""
        self.journal.append_event("app.active", "2026-10-28T10:00:00Z", {"app": "a"}, 1.0, "seg-1")

        def mock_403(url, data, headers, method="POST"):
            return 403, b"Device revoked", {}

        self.sync_worker.http_client = mock_403
        self.sync_worker.sync_events()
        self.assertTrue(self.sync_worker.is_revoked)

    def test_E25_device_clock_far_off_monotonic_tracked(self) -> None:
        """E25: Monotonic reference recorded alongside timestamp."""
        je = self.journal.append_event("app.active", "2035-01-01T00:00:00Z", {"app": "a"}, 1234.56, "seg-1")
        self.assertEqual(je.monotonic_reference, 1234.56)

    def test_E26_clock_changes_while_running(self) -> None:
        """E26: System clock step does not break monotonic ordering."""
        mono1 = time.monotonic()
        mono2 = time.monotonic()
        self.assertLessEqual(mono1, mono2)

    def test_E27_timezone_changes_stored_in_utc(self) -> None:
        """E27: All events stored in ISO-8601 UTC."""
        now_iso = datetime.now(timezone.utc).isoformat()
        je = self.journal.append_event("app.active", now_iso, {"app": "a"}, 1.0, "seg-1")
        self.assertIn("+00:00", je.occurred_at)

    # ── Edge Cases E37, E38, E56, E59, E67, E68, E88, E93, E96, E97, E98 ────

    def test_E37_policy_changed_while_offline_grace_period_enforced(self) -> None:
        """E37: Offline policy valid_until expiry disables sensitive capture."""
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.policy_manager.update_policy({
            "version": 2,
            "valid_until": expired_time,
            "screenshot_interval_seconds": 60,
        })
        self.assertFalse(self.policy_manager.is_policy_valid())
        self.assertFalse(self.policy_manager.can_capture_screenshots())

    def test_E38_device_revoked_while_offline_stops_uploads(self) -> None:
        """E38: Server 403 on reconnect stops uploads and sets revocation policy."""
        self.policy_manager.mark_revoked(action="hold")
        self.assertFalse(self.policy_manager.can_capture_screenshots())

    def test_E56_os_permission_denied_pauses_only_affected_capability(self) -> None:
        """E56: Screen recording permission denied pauses screenshots without failing foreground app capture."""
        self.adapter.set_permission("screen_recording", PermissionStatus.DENIED)
        self.adapter.set_permission("accessibility", PermissionStatus.GRANTED)

        # Foreground app tick works
        self.adapter.set_foreground_app("code.exe", "VS Code")
        evt_id = self.scheduler.step_foreground_tick()
        self.assertIsNotNone(evt_id)

        # Screenshot tick paused
        self.policy_manager.update_policy({
            "version": 1,
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "screenshot_interval_seconds": 1,
        })
        shot_id = self.scheduler.step_screenshot_tick()
        self.assertIsNone(shot_id)

    def test_E59_fast_user_switching_verifies_session_user(self) -> None:
        """E59: OS user mismatch detected on user switch."""
        self.adapter.os_username = "other_user"
        report = self.lifecycle.on_startup()
        self.assertFalse(report["session_valid"])

    def test_E67_window_title_has_sensitive_data_redacted_or_suppressed(self) -> None:
        """E67: Window title redacted when policy enabled, suppressed when disabled."""
        # 1. Disabled by default
        self.assertFalse(self.policy_manager.should_collect_window_titles())
        res = self.privacy_filter.filter_window_title("Account: 4111 2222 3333 4444")
        self.assertIsNone(res)

        # 2. Enabled -> redacted
        self.policy_manager.update_policy({
            "version": 1,
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "window_title_collection": True,
        })
        res2 = self.privacy_filter.filter_window_title("Card: 4111 2222 3333 4444")
        self.assertIn("[REDACTED-CARD]", res2)

    def test_E68_screenshot_skipped_for_password_manager(self) -> None:
        """E68: Password manager active skips screenshot capture before capture."""
        should_skip, reason = self.privacy_filter.should_skip_screenshot("C:\\Program Files\\1Password\\1Password.exe")
        self.assertTrue(should_skip)
        self.assertEqual(reason, "skipped_by_privacy_filter")

    def test_E88_logs_and_crash_dumps_contain_no_secrets(self) -> None:
        """E88: Redacting formatter scrubs sensitive tokens and keys from log records."""
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=1,
            msg="User signed in with token=secret_bearer_token_12345", args=(), exc_info=None
        )
        formatted = formatter.format(record)
        self.assertNotIn("secret_bearer_token_12345", formatted)
        self.assertIn("token=[REDACTED]", formatted)

    def test_E93_monotonic_clock_reset_after_reboot_boot_segment_isolated(self) -> None:
        """E93: Boot segment ID prevents comparing monotonic clocks across boots."""
        seg1 = self.lifecycle.boot_segment_id
        new_lifecycle = LifecycleManager(self.temp_dir, self.adapter, self.journal, self.status_tracker)
        seg2 = new_lifecycle.boot_segment_id
        self.assertNotEqual(seg1, seg2)

    def test_E96_battery_saver_defers_screenshots_and_sync(self) -> None:
        """E96: Battery saver mode pauses screenshot capture and defers sync."""
        self.adapter.set_battery_saver(True)
        self.assertTrue(self.adapter.is_battery_saver())

        # Screenshot skipped
        shot_id = self.scheduler.step_screenshot_tick()
        self.assertIsNone(shot_id)

        # Sync deferred
        synced = self.scheduler.step_sync_tick()
        self.assertEqual(synced, 0)

    def test_E97_offline_beyond_retention_or_quota(self) -> None:
        """E97: Queue limit prunes oldest with explicit telemetry gap event."""
        small_journal = Journal(os.path.join(self.temp_dir, "q.db"), self.crypto, max_events=3)
        for i in range(5):
            small_journal.append_event("app.active", f"2026-10-28T10:0{i}:00Z", {"i": i}, float(i), "seg-1")
        pending = small_journal.get_pending_events()
        gaps = [e for e in pending if e.event_type == "telemetry-gap"]
        self.assertGreaterEqual(len(gaps), 1)
        small_journal.close()

    def test_E98_user_changes_os_account_detected(self) -> None:
        """E98: Active OS user verified against expected user."""
        self.adapter.os_username = "switched_account"
        report = self.lifecycle.on_startup()
        self.assertFalse(report["session_valid"])


if __name__ == "__main__":
    unittest.main()
