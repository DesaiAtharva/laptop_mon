"""
agent/adapters/linux/adapter.py — Production Linux Desktop Adapter Implementation.

Implements OSAdapterProtocol adhering to:
- Spec §4.2 Linux capabilities, §10.1 screen capture, and §15.1 deployment.
- Pure ctypes and system abstractions via linux_api.py (zero OS imports in core).
- E22: Key storage via Secret Service with secure local keyfile fallback.
- E56: Permissions & capabilities exposure (X11 direct, Wayland portal).
- E60: Remote desktop / VDI session detection (XRDP, VNC, SSH).
- E62: Wayland vs X11 capability mismatch handling without silent failure.
- E65: Headless and unsupported desktop environment handling without crashing.
- E94: Cross-platform JPEG/WebP compression consistency.
"""

from __future__ import annotations

import logging
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
from agent.adapters.linux.linux_api import LinuxPlatform

logger = logging.getLogger(__name__)


class LinuxAdapter:
    """
    Linux desktop OS adapter implementing OSAdapterProtocol (§4.2).
    """

    def __init__(self, linux_platform: Optional[LinuxPlatform] = None) -> None:
        self.platform = linux_platform or LinuxPlatform()

    @property
    def capabilities(self) -> Set[AdapterCapability]:
        """
        Returns dynamic capabilities matching current display server and session state (E62, E65).
        """
        session_type = self.platform.get_session_type()

        # Headless environments lack GUI display capabilities (E65)
        if session_type == SessionType.HEADLESS:
            return {
                AdapterCapability.PERMISSION_STATUS,
            }

        caps: Set[AdapterCapability] = {
            AdapterCapability.FOREGROUND_APP,
            AdapterCapability.IDLE_DETECTION,
            AdapterCapability.SESSION_LOCK,
            AdapterCapability.POWER_SLEEP,
            AdapterCapability.SCREEN_CAPTURE,
            AdapterCapability.PERMISSION_STATUS,
            AdapterCapability.MULTI_MONITOR,
        }
        return caps

    def get_session_type(self) -> SessionType:
        """Returns the current session type (console, remote desktop, headless) (E60, E65)."""
        return self.platform.get_session_type()

    def get_os_username(self) -> str:
        """Returns the currently active Linux user login name."""
        return self.platform.get_username()

    def get_foreground_app(self) -> Optional[ForegroundAppEvent]:
        """
        Returns the focused foreground window process (REQ-1-2, E62).
        Under X11: window property / proc inspection.
        Under Wayland: compositor-level portal / scope detection.
        """
        app_id, window_title, pid = self.platform.get_foreground_app()
        if not app_id:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        return ForegroundAppEvent(
            timestamp=now_str,
            app_identifier=app_id,
            window_title=window_title,
            process_id=pid,
        )

    def get_idle_seconds(self) -> float:
        """Returns seconds since last user input via XScreenSaver or logind (REQ-1-3)."""
        return self.platform.get_idle_seconds()

    def capture_screen(
        self,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 80,
    ) -> CaptureResult:
        """
        Captures screen bounded by policy limits via X11 XGetImage or Wayland Portal (REQ-1-4, E61, E94, E95).
        """
        return self.platform.capture_screen_image(
            max_width=max_width,
            max_height=max_height,
            quality=quality,
        )

    def get_permissions(self) -> Dict[str, PermissionStatus]:
        """Returns permission status for sensitive capabilities (E56, E62, E65)."""
        return {
            "screen_recording": self.platform.check_screen_recording_permission(),
            "accessibility": self.platform.check_accessibility_permission(),
        }

    def is_battery_saver(self) -> bool:
        """Returns True if Linux power-profiles-daemon or sysfs reports low power mode."""
        return self.platform.is_battery_saver()

    def get_secret(self, key_name: str, fallback_dir: Optional[str] = None) -> Optional[bytes]:
        """Retrieves encryption key from Secret Service or local keyfile (E22)."""
        return self.platform.get_secret(key_name, fallback_dir=fallback_dir)

    def set_secret(self, key_name: str, secret: bytes, fallback_dir: Optional[str] = None) -> bool:
        """Stores encryption key in Secret Service or local keyfile with 0600 permissions (E22)."""
        return self.platform.set_secret(key_name, secret, fallback_dir=fallback_dir)

    def get_os_info(self) -> Dict[str, Any]:
        """Returns Linux distro info, display server, and display topology (E61, E62)."""
        displays = self.platform.get_display_topology()
        is_wayland = self.platform.is_wayland()
        session_type = self.platform.get_session_type()

        distro_info = "Linux"
        try:
            if hasattr(platform, "freedesktop_os_release"):
                release_info = platform.freedesktop_os_release()
                distro_info = f"{release_info.get('NAME', 'Linux')} {release_info.get('VERSION_ID', '')}".strip()
        except Exception:
            pass

        return {
            "os_name": "Linux",
            "distro": distro_info,
            "kernel": platform.release(),
            "machine": platform.machine(),
            "display_server": "Wayland" if is_wayland else "X11" if session_type != SessionType.HEADLESS else "None",
            "session_type": session_type.value,
            "display_count": len(displays),
            "displays": displays,
        }
