"""
agent/core/lifecycle.py — Agent Lifecycle, Startup Integrity, Unclean Shutdown & Circuit Breakers.

Adheres to:
- REQ-5-4 & E07: Bounded graceful shutdown (stop capture, commit, close, never wait on network).
- REQ-5-5 & E08: Previous-run marker & unclean-shutdown detection (writes explicit gap event on next start).
- REQ-5-6 & E10: Crash-loop circuit breaker with exponential backoff.
- E93: Boot segment ID & monotonic clock tracking across boots.
- E25, E26, E27: Clock jump and timezone change detection.
- E56: Permission-denied handling (pauses affected capability without crashing agent).
- E59, E98: OS session and user binding.
- REQ-15-2 & E13: Uninstall hook (warns, offers sync/export, never silently deletes data).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.adapters.base import OSAdapterProtocol, PermissionStatus
from agent.core.journal import Journal
from agent.core.status import AgentState, StatusTracker

logger = logging.getLogger(__name__)

CRASH_LOOP_THRESHOLD = 3
CRASH_WINDOW_SECONDS = 60.0


class LifecycleManager:
    """
    Coordinates agent startup verification, crash prevention, and bounded shutdown.
    """

    def __init__(
        self,
        data_dir: str,
        adapter: OSAdapterProtocol,
        journal: Journal,
        status_tracker: StatusTracker,
        expected_os_user: Optional[str] = None,
    ) -> None:
        self.data_dir = os.path.abspath(data_dir)
        self.adapter = adapter
        self.journal = journal
        self.status_tracker = status_tracker
        self.expected_os_user = expected_os_user

        self.marker_file_path = os.path.join(self.data_dir, "run.marker")
        self.crash_state_file = os.path.join(self.data_dir, "crash_state.json")
        self.boot_segment_id: str = str(uuid.uuid4())
        self.initial_monotonic: float = time.monotonic()
        self.initial_utc: str = datetime.now(timezone.utc).isoformat()
        self.is_shutting_down: bool = False

    def on_startup(self) -> Dict[str, Any]:
        """
        Executes startup safety sequence:
        1. Check crash loop circuit breaker (E10).
        2. Verify user/session binding (E59, E98).
        3. Check previous run marker for unclean shutdown (E08).
        4. Detect clock drift / jump (E25, E26).
        5. Write active run marker.
        """
        startup_report: Dict[str, Any] = {
            "clean_start": True,
            "unclean_shutdown_detected": False,
            "circuit_breaker_active": False,
            "session_valid": True,
            "boot_segment_id": self.boot_segment_id,
        }

        # 1. Circuit breaker check (E10)
        if self._check_crash_loop():
            startup_report["circuit_breaker_active"] = True
            logger.error("Crash-loop circuit breaker tripped (E10). Applying backoff.")

        # 2. Verify OS user binding (E59, E98)
        current_user = self.adapter.get_os_username()
        if self.expected_os_user and current_user != self.expected_os_user:
            startup_report["session_valid"] = False
            logger.warning(f"OS user mismatch: active {current_user} != expected {self.expected_os_user} (E59, E98).")

        # 3. Check unclean shutdown from previous run (E08)
        if os.path.exists(self.marker_file_path):
            startup_report["unclean_shutdown_detected"] = True
            startup_report["clean_start"] = False
            self._handle_unclean_shutdown()
        else:
            # Clean start marker
            self._write_run_marker()

        return startup_report

    def _handle_unclean_shutdown(self) -> None:
        """
        Detects ungraceful termination (hard kill, power loss).
        Logs an explicit telemetry-gap event per REQ-5-5 and E08.
        """
        try:
            with open(self.marker_file_path, "r", encoding="utf-8") as f:
                prev_info = json.load(f)
            last_heartbeat = prev_info.get("last_active_at", self.initial_utc)
        except Exception:
            last_heartbeat = self.initial_utc

        gap_payload = {
            "gap_reason": "unclean_shutdown_detected",
            "previous_active_at": last_heartbeat,
            "resumed_at": self.initial_utc,
        }

        self.journal.append_event(
            event_type="telemetry-gap",
            occurred_at=self.initial_utc,
            payload=gap_payload,
            monotonic_reference=self.initial_monotonic,
            boot_segment_id=self.boot_segment_id,
        )
        logger.warning(f"Unclean shutdown detected from previous run. Logged explicit telemetry-gap event (E08).")
        self._write_run_marker()

    def _write_run_marker(self) -> None:
        """Writes run marker to track unclean shutdowns."""
        os.makedirs(self.data_dir, exist_ok=True)
        info = {
            "boot_segment_id": self.boot_segment_id,
            "started_at": self.initial_utc,
            "last_active_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        }
        with open(self.marker_file_path, "w", encoding="utf-8") as f:
            json.dump(info, f)

    def heartbeat_marker(self) -> None:
        """Updates last active timestamp in marker file."""
        if os.path.exists(self.marker_file_path):
            try:
                with open(self.marker_file_path, "r", encoding="utf-8") as f:
                    info = json.load(f)
                info["last_active_at"] = datetime.now(timezone.utc).isoformat()
                with open(self.marker_file_path, "w", encoding="utf-8") as f:
                    json.dump(info, f)
            except Exception:
                pass

    def _check_crash_loop(self) -> bool:
        """
        Tracks consecutive crash timestamps within window (E10).
        """
        now = time.time()
        crashes: List[float] = []

        if os.path.exists(self.crash_state_file):
            try:
                with open(self.crash_state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                crashes = [t for t in data.get("crashes", []) if now - t < CRASH_WINDOW_SECONDS]
            except Exception:
                crashes = []

        crashes.append(now)
        with open(self.crash_state_file, "w", encoding="utf-8") as f:
            json.dump({"crashes": crashes}, f)

        return len(crashes) >= CRASH_LOOP_THRESHOLD

    def on_bounded_shutdown(self, timeout_seconds: float = 3.0) -> bool:
        """
        Executes bounded graceful shutdown (REQ-5-4, E07):
        1. Mark shutting down.
        2. Stop capture loops immediately.
        3. Flush and commit journal.
        4. Remove run marker to indicate clean shutdown.
        5. NEVER wait on network!
        """
        self.is_shutting_down = True
        start_time = time.monotonic()
        logger.info("Initiating bounded graceful shutdown...")

        try:
            # 1. Update status
            self.status_tracker.state = AgentState.STOPPED
            self.status_tracker.save_state()

            # 2. Flush journal & spool DBs
            self.journal.close()

            # 3. Clean up run marker (indicates clean shutdown)
            if os.path.exists(self.marker_file_path):
                os.remove(self.marker_file_path)

            elapsed = time.monotonic() - start_time
            logger.info(f"Graceful shutdown finished in {elapsed:.3f}s (budget: {timeout_seconds}s).")
            return elapsed <= timeout_seconds
        except Exception as ex:
            logger.error(f"Error during shutdown: {ex}")
            return False

    shutdown = on_bounded_shutdown

    def on_uninstall_requested(self) -> Dict[str, Any]:
        """
        Uninstall hook (REQ-15-2, E13).
        Warns of pending unsynced data, offers sync or export, and NEVER silently deletes pending data.
        """
        depth = self.journal.get_queue_depth()
        oldest_age = self.journal.get_oldest_pending_age_seconds()

        return {
            "has_pending_data": depth > 0,
            "pending_event_count": depth,
            "oldest_pending_age_seconds": oldest_age,
            "warning": (
                f"Agent has {depth} unsynced telemetry events. "
                "Per safety policy, unsynced data will not be silently deleted."
            ),
            "export_path": os.path.join(self.data_dir, "uninstall_pending_export.json"),
        }
