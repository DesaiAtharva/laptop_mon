"""
agent/adapters/macos/adapter.py — Production macOS Adapter Implementation.

Implements OSAdapterProtocol adhering to:
- Spec §4.2 macOS capabilities & §10.1 screen capture rules.
- Pure ctypes macOS API calls via macos_api.py (zero OS imports in core).
- E14: OS update or reboot verification.
- E56: Permissions & capabilities exposure (Screen Recording, Accessibility).
- E59: Fast user switching and console session resolution.
- E61: Multi-monitor display topology discovery and bounded capture.
- E63: macOS permission reset detection and prompt loop avoidance.
"""

from __future__ import annotations

import logging
import os
import platform
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from agent.adapters.base import (
    AdapterCapability,
    CaptureResult,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    SessionType,
)
from agent.adapters.macos.macos_api import MacOSPlatform

logger = logging.getLogger(__name__)


class MacOSAdapter:
    """
    macOS desktop OS adapter implementing OSAdapterProtocol (§4.2).
    """

    def __init__(self, macos_platform: Optional[MacOSPlatform] = None) -> None:
        self.platform = macos_platform or MacOSPlatform()
        self._capabilities: Set[AdapterCapability] = {
            AdapterCapability.FOREGROUND_APP,
            AdapterCapability.IDLE_DETECTION,
            AdapterCapability.SESSION_LOCK,
            AdapterCapability.POWER_SLEEP,
            AdapterCapability.SCREEN_CAPTURE,
            AdapterCapability.PERMISSION_STATUS,
            AdapterCapability.MULTI_MONITOR,
        }

    @property
    def capabilities(self) -> Set[AdapterCapability]:
        """Returns the set of capabilities supported by the macOS adapter."""
        return set(self._capabilities)

    def get_session_type(self) -> SessionType:
        """Returns the current interactive session type (console, remote desktop, headless)."""
        return self.platform.get_session_type()

    def get_os_username(self) -> str:
        """Returns the currently active GUI console username (E59)."""
        return self.platform.get_console_username()

    def get_foreground_app(self) -> Optional[ForegroundAppEvent]:
        """Returns the currently focused foreground application (bundle identifier)."""
        bundle_id, window_title, pid = self.platform.get_foreground_app()
        if not bundle_id:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        return ForegroundAppEvent(
            timestamp=now_str,
            app_identifier=bundle_id,
            window_title=window_title if window_title else None,
            process_id=pid,
        )

    def get_idle_seconds(self) -> float:
        """Returns seconds since last keyboard or mouse input."""
        return self.platform.get_idle_seconds()

    def capture_screen(
        self,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 80,
    ) -> CaptureResult:
        """Captures primary and secondary displays bounded by resolution caps (§10.1, E61, E95)."""
        return self.platform.capture_screen_image(
            max_width=max_width,
            max_height=max_height,
            quality=quality,
        )

    def get_permissions(self) -> Dict[str, PermissionStatus]:
        """Returns permission status for sensitive macOS capabilities without prompting loops (E56, E63)."""
        return {
            "screen_capture": self.platform.check_screen_recording_permission(),
            "accessibility": self.platform.check_accessibility_permission(),
        }

    def verify_after_os_update(self) -> Dict[str, Any]:
        """Re-verifies permissions and policy after macOS system update or reboot (E14, E63)."""
        perms = self.get_permissions()
        screen_ok = perms.get("screen_capture") == PermissionStatus.GRANTED
        acc_ok = perms.get("accessibility") == PermissionStatus.GRANTED
        all_ok = screen_ok and acc_ok

        report = {
            "os_update_verified": True,
            "permissions_ok": all_ok,
            "permissions": perms,
            "instructions": (
                "Re-authorization required in macOS System Settings > Privacy & Security "
                "for Screen Recording or Accessibility (E63)."
                if not all_ok
                else "All permissions intact."
            ),
        }
        if not all_ok:
            logger.warning("Permissions reset detected after macOS update: %s (E63)", report["instructions"])
        return report

    def is_battery_saver(self) -> bool:
        """Returns True if macOS Low Power Mode is active."""
        return self.platform.is_battery_saver()

    def get_os_info(self) -> Dict[str, Any]:
        """Returns macOS release version, build, chip architecture, and multi-display topology (E61)."""
        displays = self.platform.get_display_topology()
        mac_ver = platform.mac_ver()[0] or "14.0"
        return {
            "os_name": "macOS",
            "version": mac_ver,
            "release": platform.release(),
            "machine": platform.machine(),
            "display_count": len(displays),
            "displays": displays,
        }
