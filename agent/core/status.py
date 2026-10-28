"""
agent/core/status.py — Monitoring State Tracker & Discoverability.

Adheres to:
- REQ-2-2 & §2.1, §11.3: First-run notice acknowledgement enforcement. Capture prohibited before acknowledgement.
- REQ-4-3 & E11: Closing tray UI does NOT stop capture.
- REQ-4-4 & E11: Monitoring state remains discoverable via local status file / IPC state when UI is closed.
- REQ-1-1 & E12: Explicit authorized employee stop is honored and never silently reversed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AgentState(Enum):
    UNACKNOWLEDGED = "unacknowledged"  # First-run notice not yet acknowledged
    RUNNING = "running"                # Monitoring active
    PAUSED = "paused"                  # Paused due to policy, lock, battery, or permission
    STOPPED = "stopped"                # Explicitly stopped by employee / admin


@dataclass
class AgentStatusInfo:
    state: str
    is_capturing: bool
    first_run_acknowledged: bool
    explicitly_stopped: bool
    policy_version: int
    queue_depth: int
    last_event_at: Optional[str]
    last_sync_at: Optional[str]
    os_user: str
    device_id: Optional[str]
    stop_reason: Optional[str]
    updated_at: str


class StatusTracker:
    """
    Maintains persistent agent monitoring state and exposes it for UI / CLI discovery.
    """

    def __init__(self, state_file_path: str) -> None:
        self.state_file_path = os.path.abspath(state_file_path)
        self.state: AgentState = AgentState.UNACKNOWLEDGED
        self.first_run_acknowledged: bool = False
        self.explicitly_stopped: bool = False
        self.stop_reason: Optional[str] = None
        self.policy_version: int = 1
        self.queue_depth: int = 0
        self.last_event_at: Optional[str] = None
        self.last_sync_at: Optional[str] = None
        self.os_user: str = ""
        self.device_id: Optional[str] = None

        self._load_state()

    def _load_state(self) -> None:
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.first_run_acknowledged = data.get("first_run_acknowledged", False)
                self.explicitly_stopped = data.get("explicitly_stopped", False) or (data.get("state") == AgentState.STOPPED.value)
                self.stop_reason = data.get("stop_reason")
                self.policy_version = data.get("policy_version", 1)
                self.device_id = data.get("device_id")
                self.os_user = data.get("os_user", "")

                if self.explicitly_stopped or data.get("state") == AgentState.STOPPED.value:
                    self.state = AgentState.STOPPED
                    self.explicitly_stopped = True
                elif not self.first_run_acknowledged:
                    self.state = AgentState.UNACKNOWLEDGED
                else:
                    self.state = AgentState.RUNNING
            except Exception as ex:
                logger.error(f"Error loading state file: {ex}")

    def save_state(self) -> None:
        """Saves discoverable status to disk (REQ-4-4, E11)."""
        os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        info = AgentStatusInfo(
            state=self.state.value,
            is_capturing=self.can_capture(),
            first_run_acknowledged=self.first_run_acknowledged,
            explicitly_stopped=self.explicitly_stopped,
            policy_version=self.policy_version,
            queue_depth=self.queue_depth,
            last_event_at=self.last_event_at,
            last_sync_at=self.last_sync_at,
            os_user=self.os_user,
            device_id=self.device_id,
            stop_reason=self.stop_reason,
            updated_at=now_iso,
        )
        tmp_path = f"{self.state_file_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(asdict(info), f, indent=2)
        os.replace(tmp_path, self.state_file_path)

    def acknowledge_first_run(self) -> None:
        """Records employee acknowledgement of the first-run privacy notice (REQ-2-2)."""
        self.first_run_acknowledged = True
        if not self.explicitly_stopped:
            self.state = AgentState.RUNNING
        self.save_state()

    def stop_monitoring(self, reason: str = "employee_exit") -> None:
        """
        Explicit authorized stop requested by employee (REQ-1-1, E12).
        Must be preserved across restarts and NEVER silently reversed.
        """
        self.explicitly_stopped = True
        self.stop_reason = reason
        self.state = AgentState.STOPPED
        self.save_state()
        logger.info(f"Monitoring explicitly stopped ({reason}). Will not resume without explicit authorization.")

    def resume_monitoring(self) -> None:
        """Explicit authorized resume."""
        if not self.first_run_acknowledged:
            self.state = AgentState.UNACKNOWLEDGED
            return
        self.explicitly_stopped = False
        self.stop_reason = None
        self.state = AgentState.RUNNING
        self.save_state()

    def can_capture(self) -> bool:
        """Returns True only if first-run notice is acknowledged and monitoring is not stopped."""
        if not self.first_run_acknowledged:
            return False
        if self.explicitly_stopped or self.state == AgentState.STOPPED:
            return False
        return True

    def get_discoverable_status(self) -> Dict[str, Any]:
        """Provides status dictionary for external inspection when UI is closed (REQ-4-4)."""
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "state": self.state.value,
            "is_capturing": self.can_capture(),
            "first_run_acknowledged": self.first_run_acknowledged,
        }
