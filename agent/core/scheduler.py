"""
agent/core/scheduler.py — Resource-Aware Event-Driven Scheduler.

Adheres to:
- Lightness rules: Event-driven where possible; long intervals and backoff when idle, locked, or on battery saver.
- E56: Permission-denied states pause ONLY the affected capability.
- E58: Sleep/wake state transitions pause capture and reconcile wake events.
- E96: Throttling / deferring nonessential capture & upload under battery saver or CPU pressure.
- REQ-2-2 & §2.1: Prohibits capture if first-run notice not acknowledged.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent.adapters.base import (
    AdapterCapability,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    PowerEventType,
    SessionEventType,
)
from agent.core.diagnostics import DiagnosticsCollector
from agent.core.journal import Journal
from agent.core.lifecycle import LifecycleManager
from agent.core.policy import PolicyManager
from agent.core.privacy_filter import PrivacyFilter
from agent.core.spool import ScreenshotSpool
from agent.core.status import StatusTracker
from agent.core.sync import SyncWorker

logger = logging.getLogger(__name__)


class AgentScheduler:
    """
    Coordinates capture, spooling, synchronization, and health reporting ticks.
    """

    def __init__(
        self,
        adapter: OSAdapterProtocol,
        journal: Journal,
        spool: ScreenshotSpool,
        policy_manager: PolicyManager,
        privacy_filter: PrivacyFilter,
        status_tracker: StatusTracker,
        lifecycle: LifecycleManager,
        sync_worker: SyncWorker,
        diagnostics: DiagnosticsCollector,
    ) -> None:
        self.adapter = adapter
        self.journal = journal
        self.spool = spool
        self.policy_manager = policy_manager
        self.privacy_filter = privacy_filter
        self.status_tracker = status_tracker
        self.lifecycle = lifecycle
        self.sync_worker = sync_worker
        self.diagnostics = diagnostics

        # State tracking
        self.last_foreground_app: Optional[str] = None
        self.last_screenshot_mono: float = 0.0
        self.last_sync_mono: float = 0.0
        self.last_heartbeat_mono: float = 0.0
        self.is_currently_idle: bool = False
        self.is_currently_locked: bool = False
        self.is_currently_asleep: bool = False

    def step_foreground_tick(self) -> Optional[str]:
        """
        Polls foreground window app if adapter doesn't push events.
        Captures transitions, applies privacy filter, logs event to journal.
        Returns event_id if an event was generated, or None.
        """
        if not self.status_tracker.can_capture():
            return None

        perms = self.adapter.get_permissions()
        # Accessibility permission check (E56)
        if perms.get("accessibility") == PermissionStatus.DENIED:
            logger.debug("Foreground tracking paused: accessibility permission denied (E56).")
            return None

        event = self.adapter.get_foreground_app()
        if not event:
            return None

        app_id = event.app_identifier
        # Filter window title per policy (E67)
        filtered_title = self.privacy_filter.filter_window_title(event.window_title)

        # Check if foreground application changed
        if app_id != self.last_foreground_app:
            self.last_foreground_app = app_id
            payload = {
                "app_identifier": app_id,
                "window_title": filtered_title,
                "process_id": event.process_id,
            }
            je = self.journal.append_event(
                event_type="app.active",
                occurred_at=event.timestamp,
                payload=payload,
                monotonic_reference=time.monotonic(),
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            self.status_tracker.last_event_at = event.timestamp
            return je.id

        return None

    def step_idle_tick(self) -> Optional[str]:
        """
        Evaluates user inactivity against policy idle_threshold_seconds (E70).
        """
        if not self.status_tracker.can_capture():
            return None

        policy = self.policy_manager.get_effective_policy()
        threshold = policy.idle_threshold_seconds if policy else 300
        idle_sec = self.adapter.get_idle_seconds()
        now_iso = datetime.now(timezone.utc).isoformat()

        if idle_sec >= threshold and not self.is_currently_idle:
            self.is_currently_idle = True
            je = self.journal.append_event(
                event_type="session.idle_start",
                occurred_at=now_iso,
                payload={"idle_seconds": idle_sec, "threshold_seconds": threshold},
                monotonic_reference=time.monotonic(),
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id

        elif idle_sec < threshold and self.is_currently_idle:
            self.is_currently_idle = False
            je = self.journal.append_event(
                event_type="session.idle_end",
                occurred_at=now_iso,
                payload={"idle_seconds": idle_sec},
                monotonic_reference=time.monotonic(),
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id

        return None

    def step_screenshot_tick(self) -> Optional[str]:
        """
        Evaluates screenshot capture interval, privacy filter, and quota.
        """
        if not self.status_tracker.can_capture():
            return None

        # Fail closed if policy is expired or sensitive capture disallowed (E37)
        if not self.policy_manager.can_capture_screenshots():
            return None

        # Pause on battery saver (E96)
        if self.adapter.is_battery_saver():
            logger.debug("Screenshot skipped: battery saver active (E96).")
            return None

        # Pause if locked or asleep
        if self.is_currently_locked or self.is_currently_asleep:
            return None

        # Check screen recording permission (E56)
        perms = self.adapter.get_permissions()
        if perms.get("screen_recording") == PermissionStatus.DENIED:
            logger.debug("Screenshot skipped: screen recording permission denied (E56).")
            return None

        policy = self.policy_manager.get_effective_policy()
        interval = policy.screenshot_interval_seconds if policy else 300
        now_mono = time.monotonic()

        if now_mono - self.last_screenshot_mono < interval:
            return None

        self.last_screenshot_mono = now_mono

        # Privacy filter check: is current app sensitive or password manager? (E68)
        fg_app = self.adapter.get_foreground_app()
        if fg_app:
            should_skip, skip_reason = self.privacy_filter.should_skip_screenshot(
                fg_app.app_identifier, fg_app.window_title
            )
            if should_skip:
                now_iso = datetime.now(timezone.utc).isoformat()
                je = self.journal.append_event(
                    event_type="screenshot.skipped",
                    occurred_at=now_iso,
                    payload={"skipped": True, "reason": "privacy_filter"},
                    monotonic_reference=now_mono,
                    boot_segment_id=self.lifecycle.boot_segment_id,
                )
                return je.id

        # Capture
        capture = self.adapter.capture_screen()
        now_iso = datetime.now(timezone.utc).isoformat()

        if capture.is_skipped or not capture.image_bytes:
            je = self.journal.append_event(
                event_type="screenshot.skipped",
                occurred_at=now_iso,
                payload={"skipped": True, "reason": "adapter_skipped"},
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id

        # Spool screenshot
        spooled = self.spool.spool_screenshot(
            image_bytes=capture.image_bytes,
            captured_at=now_iso,
            metadata={"width": capture.width, "height": capture.height, "format": capture.format},
        )
        if spooled:
            # Also record screenshot captured metadata event in journal
            je = self.journal.append_event(
                event_type="screenshot.captured",
                occurred_at=now_iso,
                payload={
                    "screenshot_id": spooled.screenshot_id,
                    "width": capture.width,
                    "height": capture.height,
                    "checksum": spooled.sha256_checksum,
                },
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return spooled.screenshot_id

        return None

    def on_power_event(self, event_type: PowerEventType) -> Optional[str]:
        """Handles power state change (sleep/wake) (E58)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        now_mono = time.monotonic()

        if event_type == PowerEventType.SLEEP:
            self.is_currently_asleep = True
            je = self.journal.append_event(
                event_type="session.sleep",
                occurred_at=now_iso,
                payload={"power_state": "sleep"},
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id
        elif event_type == PowerEventType.WAKE:
            self.is_currently_asleep = False
            je = self.journal.append_event(
                event_type="session.wake",
                occurred_at=now_iso,
                payload={"power_state": "wake"},
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id
        return None

    def on_session_event(self, event_type: SessionEventType) -> Optional[str]:
        """Handles session lock/unlock/switch."""
        now_iso = datetime.now(timezone.utc).isoformat()
        now_mono = time.monotonic()

        if event_type == SessionEventType.LOCK:
            self.is_currently_locked = True
            je = self.journal.append_event(
                event_type="session.lock",
                occurred_at=now_iso,
                payload={"session_state": "locked"},
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id
        elif event_type == SessionEventType.UNLOCK:
            self.is_currently_locked = False
            je = self.journal.append_event(
                event_type="session.unlock",
                occurred_at=now_iso,
                payload={"session_state": "unlocked"},
                monotonic_reference=now_mono,
                boot_segment_id=self.lifecycle.boot_segment_id,
            )
            return je.id
        return None

    def step_sync_tick(self) -> int:
        """Runs periodic sync and heartbeat upload."""
        # Defer uploads under battery saver or CPU pressure (E96)
        if self.adapter.is_battery_saver():
            return 0

        synced_events = self.sync_worker.sync_events()
        self.sync_worker.sync_screenshots()

        # Heartbeat tick (e.g. every 60s)
        now_mono = time.monotonic()
        if now_mono - self.last_heartbeat_mono > 60.0:
            self.last_heartbeat_mono = now_mono
            hb_payload = self.diagnostics.build_heartbeat_payload(
                queue_depth=self.journal.get_queue_depth(),
                oldest_pending_age_seconds=self.journal.get_oldest_pending_age_seconds(),
                permissions=self.adapter.get_permissions(),
                last_sync_at=self.status_tracker.last_sync_at,
            )
            self.sync_worker.send_heartbeat(hb_payload)

        return synced_events
